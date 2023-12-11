#!/usr/bin/env python3

"""
This module collects a number of statistic enum classes, where every enum member
represents a different specific statistic.

The statistics are implemented via:
  - a `test` method that determines if a given entity (e.g. a registration or a course)
   fits that statistic
  - a `_get_query_aux` method that constructs fields, constraints and sorting order
   to construct a Query object for that statistic.

A couple of abstract classes exist that help to construct the queries, as well as
extend these statistics to cover multiple tracks and or parts.

Additionally there are a number of small helper functions used in the enum methods.
"""
import abc
import datetime
import enum
import itertools
from collections.abc import Collection, Iterator, Sequence
from typing import Optional

import cdedb.database.constants as const
import cdedb.models.event as models
from cdedb.common import AgeClasses, CdEDBObject, CdEDBObjectMap, deduct_years, unwrap
from cdedb.common.n_ import n_
from cdedb.common.query import (
    Query, QueryConstraint, QueryOperators, QueryOrder, QueryScope,
)
from cdedb.common.sorting import xsorted

RPS = const.RegistrationPartStati

StatQueryAux = tuple[list[str], list[QueryConstraint], list[QueryOrder]]

__all__ = ['EventRegistrationPartStatistic', 'EventCourseStatistic',
           'EventRegistrationTrackStatistic', 'EventRegistrationInXChoiceGrouper']


# Helper functions that are frequently used when testing stats.
def _is_participant(reg_part: CdEDBObject) -> bool:
    return reg_part['status'] == RPS.participant


# Helper functions to build query constraints frequently used by stats.
def _status_constraint(part: models.EventPart, status: const.RegistrationPartStati,
                       negate: bool = False) -> QueryConstraint:
    return (
        f"part{part.id}.status",
        QueryOperators.unequal if negate else QueryOperators.equal,
        status.value,
    )


def _participant_constraint(part: models.EventPart) -> QueryConstraint:
    return _status_constraint(part, RPS.participant)


def _involved_constraint(part: models.EventPart) -> QueryConstraint:
    return (f"part{part.id}.status", QueryOperators.oneof,
            tuple(status.value for status in RPS if status.is_involved()))


def _has_to_pay_constraint(part: models.EventPart) -> QueryConstraint:
    return (f"part{part.id}.status", QueryOperators.oneof,
            tuple(status.value for status in RPS if status.has_to_pay()))


def _present_constraint(part: models.EventPart) -> QueryConstraint:
    return (f"part{part.id}.status", QueryOperators.oneof,
            tuple(status.value for status in RPS if status.is_present()))


def _age_constraint(part: models.EventPart, max_age: int, min_age: int = None,
                    ) -> QueryConstraint:
    min_date = deduct_years(part.part_begin, max_age)
    if min_age is None:
        return ('persona.birthday', QueryOperators.greater, min_date)
    else:
        # Add an offset of one, because `between` is inclusive on both ends.
        min_date += datetime.timedelta(days=1)
        max_date = deduct_years(part.part_begin, min_age)
        return ('persona.birthday', QueryOperators.between, (min_date, max_date))


# Helper function to construct ordering for waitlist queries.
def _waitlist_order(event: models.Event, part: models.EventPart) -> list[QueryOrder]:
    ret = []
    if field := part.waitlist_field:
        ret.append((f'reg_fields.xfield_{field.field_name}', True))
    return ret + [('reg.payment', True), ('ctime.creation_time', True)]


def merge_constraints(*constraints: QueryConstraint) -> Optional[QueryConstraint]:
    """
    Helper function to try to merge a collection of query constraints into a single one.

    In order to be mergable all constraints must have the same `QueryOperator` and the
    same value. All differing constraint fields are joined together, respecting order.

    >>> merge_constraints(("part1.status", "=", 1), ("part2.status", "=", 1))
    QueryConstraint(field='part1.status,part2.status', op='=', value=1)
    >>> merge_constraints(("part2.status", "=", 1), ("part1.status", "=", 1))
    QueryConstraint(field='part2.status,part1.status', op='=', value=1)
    >>> merge_constraints(("part1.status", "=", 1), ("part1.status", "=", 1))
    QueryConstraint(field='part1.status', op='=', value=1)
    >>> merge_constraints(("a", "=", 1), ("a", "=", 1), ("b", "=", 1))
    QueryConstraint(field='a,b', op='=', value=1)
    >>> merge_constraints(("part1.status", "=", 1), ("part1.status", "!=", 1))

    >>> merge_constraints(("part1.status", "=", 1), ("part1.status", "=", 2))

    """
    # Fields will be collected via the keys of this dict, with all values being None.
    # This ensures uniqueness, while preserving order, which is not possible with sets.
    fields: dict[str, None] = {}
    operators, values = set(), set()
    for con in constraints:
        field, op, value = con
        fields[field] = None
        operators.add(op)
        values.add(value)
    if len(operators) != 1 or len(values) != 1:
        return None
    return (",".join(fields), unwrap(operators), unwrap(values))


def merge_queries(base_query: Query, *queries: Query) -> Optional[Query]:
    """Return a new query, which is derived from the base query and the merged
    constraints of the other queries.

    Mergable queries need to have the same number of constraints each, and have them
    in the same order.

    Returns None if the queries could not be merged.
    """
    if not queries:
        return None
    all_fields = itertools.chain.from_iterable(q.fields_of_interest for q in queries)
    constraint_lists = [q.constraints for q in queries]
    num_constraints = len(constraint_lists[0])
    if any(len(c) != num_constraints for c in constraint_lists):
        return None
    merged_constraints = []
    for i in range(num_constraints):
        new_constraint = merge_constraints(*(clist[i] for clist in constraint_lists))

        # If the constraints could not be merged or the new constraint is not a valid
        # field, exit gracefully.
        if new_constraint is None or new_constraint[0] not in base_query.spec:
            return None
        merged_constraints.append(new_constraint)
    query_orders = {tuple(q.order) for q in queries}
    return Query(
        scope=base_query.scope, spec=base_query.spec,
        fields_of_interest=set(base_query.fields_of_interest) | set(all_fields),
        constraints=merged_constraints,
        order=unwrap(query_orders) if len(query_orders) == 1 else base_query.order,
    )


def get_id_constraint(id_field: str, entity_ids: Collection[int]) -> QueryConstraint:
    if entity_ids:
        return (id_field, QueryOperators.oneof, list(entity_ids))
    else:
        return (id_field, QueryOperators.empty, None)


class StatisticMixin:
    """Helper class for basic query construction shared across"""
    id_field: str
    name: str

    @abc.abstractmethod
    def test(self, event: models.Event, entity: CdEDBObject, context_id: int) -> bool:
        """Determine whether the given entity fits this stat for the given context."""

    @abc.abstractmethod
    def _get_query_aux(self, event: models.Event, context_id: int) -> StatQueryAux:
        """Construct query fields, constraints and order for this stat and a context."""

    @staticmethod
    @abc.abstractmethod
    def _get_base_query(event: models.Event) -> Query:
        """Create a query object to base all queries for these stats on."""

    def get_query(self, event: models.Event, context_id: int) -> Query:
        """Construct the actual query from the base and stat specifix query aux."""
        query = self._get_base_query(event)
        fields, constraints, order = self._get_query_aux(event, context_id)
        query.fields_of_interest.extend(fields)
        query.constraints.extend(constraints)
        # Prepend the specific order.
        query.order = order + query.order
        return query

    @abc.abstractmethod
    def get_query_part_group(self, event: models.Event, part_group_id: int,
                             registration_ids: Collection[int]) -> Query:
        """Construct a merged query for all things in a part group."""

    def get_query_by_ids(self, event: models.Event, entity_ids: Collection[int],
                         ) -> Query:
        """This queries information by exhaustion by listing all relevant ids."""
        query = self._get_base_query(event)
        query.constraints.append(get_id_constraint(self.id_field, entity_ids))
        return query

    @abc.abstractmethod
    def is_mergeable(self) -> bool:
        """Determine whether or not queries of this type can be merged.

        Queries with correlations between two of their constraints can syntactically be
        merged but are semantically incorrect.
        """

    @staticmethod
    def get_part_ids(event: models.Event, *, part_group_id: int) -> Sequence[int]:
        return tuple(event.part_groups[part_group_id].parts.keys())

    @staticmethod
    def get_track_ids(event: models.Event, *, part_id: int = None,
                      part_group_id: int = None) -> Sequence[int]:
        """Determine the relevant track ids for the given part (group) id."""
        if part_id:
            return tuple(event.parts[part_id].tracks.keys())
        if part_group_id:
            parts = event.part_groups[part_group_id].parts.values()
            return tuple(itertools.chain.from_iterable(p.tracks for p in parts))
        return ()

    @abc.abstractmethod
    def get_link_id(self, *, track_id: int = None, part_id: int = None,
                    part_group_id: int = None) -> str:
        """Build an id for the link to the related query."""


# This class is still abstract, but adding abc.ABC doesn't play nice with enum.Enum.
class StatisticPartMixin(StatisticMixin):  # pylint: disable=abstract-method
    """
    Helper class for methods to delegate tests and query construction for part stats.
    """

    def test_part_group(self, event: models.Event, entity: CdEDBObject,
                        part_group_id: int) -> bool:
        """Determine whether the entity fits this stat for any track in a part group."""
        return any(self.test(event, entity, track_id) for track_id
                   in self.get_part_ids(event, part_group_id=part_group_id))

    def get_query_part_group(self, event: models.Event, part_group_id: int,
                             registration_ids: Collection[int]) -> Query:
        """Construct queries for every part in a given part group, then merge them."""
        if self.is_mergeable():
            queries = [self.get_query(event, part_id) for part_id
                       in self.get_part_ids(event, part_group_id=part_group_id)]
            if ret := merge_queries(self._get_base_query(event), *queries):
                return ret
        return self.get_query_by_ids(event, registration_ids)

    def get_link_id(self, *, track_id: int = None, part_id: int = None,
                    part_group_id: int = None) -> str:
        """Build an id for the link to the related query."""
        if part_id:
            return f"part_{self.name}_{part_id}"
        elif part_group_id:
            return f"part_group_{self.name}_{part_group_id}"
        return ""


# This class is still abstract, but adding abc.ABC doesn't play nice with enum.Enum.
class StatisticTrackMixin(StatisticMixin):  # pylint: disable=abstract-method
    """
    Helper class for methods to delegate tests and query construction for track stats.
    """

    def test_part(self, event: models.Event, entity: CdEDBObject, part_id: int) -> bool:
        """Determine whether the entity fits this stat for any track in a part."""
        return any(self.test(event, entity, track_id)
                   for track_id in self.get_track_ids(event, part_id=part_id))

    def test_part_group(self, event: models.Event, entity: CdEDBObject,
                        part_group_id: int) -> bool:
        """Determine whether the entity fits this stat for any track in a part group."""
        return any(self.test(event, entity, track_id) for track_id
                   in self.get_track_ids(event, part_group_id=part_group_id))

    def get_query_part(self, event: models.Event, part_id: int,
                       registration_ids: Collection[int]) -> Query:
        """Construct queries for every track in a given part, then merge them."""
        if self.is_mergeable():
            queries = [self.get_query(event, track_id) for track_id
                       in self.get_track_ids(event, part_id=part_id)]
            if ret := merge_queries(self._get_base_query(event), *queries):
                return ret
        return self.get_query_by_ids(event, registration_ids)

    def get_query_part_group(self, event: models.Event, part_group_id: int,
                             registration_ids: Collection[int]) -> Query:
        """Construct queries for every track in a given part group, then merge them."""
        if self.is_mergeable():
            queries = [self.get_query(event, track_id) for track_id
                       in self.get_track_ids(event, part_group_id=part_group_id)]
            if ret := merge_queries(self._get_base_query(event), *queries):
                return ret
        return self.get_query_by_ids(event, registration_ids)

    def get_link_id(self, *, track_id: int = None, part_id: int = None,
                    part_group_id: int = None) -> str:
        """Build an id for the link to the related query."""
        if track_id:
            return f"track_{self.name}_{track_id}"
        elif part_id:
            return f"track_part_{self.name}_{part_id}"
        elif part_group_id:
            return f"track_group_{self.name}_{part_group_id}"
        return ""


# These enums each offer a collection of statistics for the stats page.
# They implement a test and query building interface:
# A `.test` method that takes the event data and a registrations, returning
# a bool indicating whether the given registration fits that statistic.
# A `.get_query` method that builds a `Query` object of the appropriate query scope
# that will show all fitting entities for that statistic.
# The enum member values are translatable strings to be used as labels for that
# statistic. The order of member definition inidicates the order they will be displayed.


@enum.unique
class EventRegistrationPartStatistic(StatisticPartMixin, enum.Enum):
    """This enum implements statistics for registration parts.

    In addition to their string value, all members have an additional `.indent`
    attribute, which specifies the level of indentation of that statistic.
    """
    indent: int

    def __new__(cls, value: str, indent: int = 0) -> "EventRegistrationPartStatistic":
        """Custom creation method for this enum.

        Achieves that value and indentation of new members can be written using tuple
        syntax. Indentation defaults to 0.
        """
        obj = object.__new__(cls)
        obj._value_ = value
        obj.indent = indent
        obj.id_field = "reg.id"
        return obj

    pending = n_("Open Registrations")
    paid = n_("Paid"), 1
    participant = n_("Participants")
    minors = n_("All minors"), 1
    u18 = n_("U18"), 2
    u16 = n_("U16"), 2
    u14 = n_("U14"), 2
    u10 = n_("U10"), 1
    checked_in = n_("Checked-In"), 1
    not_checked_in = n_("Not Checked-In"), 1
    orgas = n_("Orgas"), 1
    waitlist = n_("Waitinglist")
    guest = n_("Guests")
    involved = n_("Total Active Registrations")
    not_paid = n_("Not Paid"), 1
    orgas_not_paid = n_("thereof Orgas"), 2
    no_parental_agreement = n_("Parental Consent Pending"), 1
    present = n_("Present")
    no_lodgement = n_("No Lodgement"), 1
    cancelled = n_("Registration Cancelled")
    rejected = n_("Registration Rejected")
    total = n_("Total Registrations")

    def is_mergeable(self) -> bool:
        return self not in {
            # The no lodgement query has a part correlation between two constraints.
            EventRegistrationPartStatistic.no_lodgement,
        }

    def test(self, event: models.Event, reg: CdEDBObject, part_id: int) -> bool:  # pylint: disable=arguments-differ
        """
        Test whether the given registration fits into this statistic for the given part.
        """
        part = reg['parts'][part_id]
        if self == self.pending:
            return part['status'] == RPS.applied
        elif self == self.paid:
            return part['status'] == RPS.applied and reg['payment']
        elif self == self.participant:
            return _is_participant(part)
        elif self == self.minors:
            return _is_participant(part) and part['age_class'].is_minor()
        elif self == self.u18:
            return _is_participant(part) and part['age_class'] == AgeClasses.u18
        elif self == self.u16:
            return _is_participant(part) and part['age_class'] == AgeClasses.u16
        elif self == self.u14:
            return _is_participant(part) and part['age_class'] == AgeClasses.u14
        elif self == self.u10:
            return _is_participant(part) and part['age_class'] == AgeClasses.u10
        elif self == self.checked_in:
            return _is_participant(part) and reg['checkin']
        elif self == self.not_checked_in:
            return _is_participant(part) and not reg['checkin']
        elif self == self.orgas:
            return _is_participant(part) and reg['persona_id'] in event.orgas
        elif self == self.waitlist:
            return part['status'] == RPS.waitlist
        elif self == self.guest:
            return part['status'] == RPS.guest
        elif self == self.involved:
            return part['status'].is_involved()
        elif self == self.not_paid:
            return part['status'].has_to_pay() and not reg['payment']
        elif self == self.orgas_not_paid:
            return (
                    EventRegistrationPartStatistic.orgas.test(event, reg, part_id)
                    and EventRegistrationPartStatistic.not_paid.test(event, reg,
                                                                     part_id))
        elif self == self.no_parental_agreement:
            return (part['status'].is_involved() and part['age_class'].is_minor()
                    and not reg['parental_agreement'])
        elif self == self.present:
            return part['status'].is_present()
        elif self == self.no_lodgement:
            return part['status'].is_present() and not part['lodgement_id']
        elif self == self.cancelled:
            return part['status'] == RPS.cancelled
        elif self == self.rejected:
            return part['status'] == RPS.rejected
        elif self == self.total:
            return part['status'] != RPS.not_applied
        else:
            raise RuntimeError(n_("Impossible."))

    def _get_query_aux(self, event: models.Event, part_id: int) -> StatQueryAux:  # pylint: disable=arguments-differ
        """
        Return fields of interest, constraints and order for this statistic for a part.
        """
        part = event.parts[part_id]
        if self == self.pending:
            return ([], [_status_constraint(part, RPS.applied)], [])
        elif self == self.paid:
            return (
                ['reg.payment'],
                [
                    _status_constraint(part, RPS.applied),
                    ('reg.payment', QueryOperators.nonempty, None),
                ],
                [],
            )
        elif self == self.participant:
            return ([], [_participant_constraint(part)], [])
        elif self == self.minors:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 18, 10)],
                [],
            )
        elif self == self.u18:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 18, 16),
                ],
                [],
            )
        elif self == self.u16:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 16, 14),
                ],
                [],
            )
        elif self == self.u14:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 14, 10),
                ],
                [],
            )
        elif self == self.u10:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 10),
                ],
                [],
            )
        elif self == self.checked_in:
            return (
                ['reg.checkin'],
                [
                    _participant_constraint(part),
                    ('reg.checkin', QueryOperators.nonempty, None),
                ],
                [],
            )
        elif self == self.not_checked_in:
            return (
                [],
                [
                    _participant_constraint(part),
                    ('reg.checkin', QueryOperators.empty, None),
                ],
                [],
            )
        elif self == self.orgas:
            return (
                [],
                [
                    _participant_constraint(part),
                    ('persona.id', QueryOperators.oneof, tuple(event.orgas)),
                ],
                [],
            )
        elif self == self.waitlist:
            return (
                ['reg.payment', 'ctime.creation_time'] + [
                    f'reg_fields.xfield_{part.waitlist_field.field_name}',
                ] if part.waitlist_field else [],
                [_status_constraint(part, RPS.waitlist)],
                _waitlist_order(event, part),
            )
        elif self == self.guest:
            return ([], [_status_constraint(part, RPS.guest)], [])
        elif self == self.involved:
            return ([f"part{part.id}.status"], [_involved_constraint(part)], [])
        elif self == self.not_paid:
            return (
                [f"part{part.id}.status"],
                [
                    _has_to_pay_constraint(part),
                    ('reg.payment', QueryOperators.empty, None),
                ],
                [],
            )
        elif self == self.orgas_not_paid:
            return (
                [f"part{part.id}.status"],
                [
                    _participant_constraint(part),
                    ('persona.id', QueryOperators.oneof, tuple(event.orgas)),
                    ('reg.payment', QueryOperators.empty, None),
                ],
                [],
            )
        elif self == self.no_parental_agreement:
            return (
                [f"part{part.id}.status"],
                [
                    _involved_constraint(part),
                    _age_constraint(part, 18, 10),
                    ('reg.parental_agreement', QueryOperators.equal, False),
                ],
                [],
            )
        elif self == self.present:
            return ([f"part{part.id}.status"], [_present_constraint(part)], [])
        elif self == self.no_lodgement:
            return (
                [f"part{part.id}.status"],
                [
                    _present_constraint(part),
                    (f"part{part.id}.lodgement_id", QueryOperators.empty, None),
                ],
                [],
            )
        elif self == self.cancelled:
            return (
                ['reg.amount_paid'],
                [_status_constraint(part, RPS.cancelled)],
                [],
            )
        elif self == self.rejected:
            return (
                ['reg.amount_paid'],
                [_status_constraint(part, RPS.rejected)],
                [],
            )
        elif self == self.total:
            return (
                [f"part{part.id}.status"],
                [_status_constraint(part, RPS.not_applied, negate=True)],
                [],
            )
        else:
            raise RuntimeError(n_("Impossible."))

    @staticmethod
    def _get_base_query(event: models.Event) -> Query:
        return Query(
            QueryScope.registration,
            event.basic_registration_query_spec,
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username'],
            constraints=[],
            order=[('persona.family_name', True), ('persona.given_names', True)],
        )


@enum.unique
class EventCourseStatistic(StatisticTrackMixin, enum.Enum):
    """This enum implements statistics for courses in course tracks."""

    def __new__(cls, value: str) -> "EventCourseStatistic":
        obj = object.__new__(cls)
        obj._value_ = value
        obj.id_field = "course.id"
        return obj

    offered = n_("Course Offers")
    cancelled = n_("Cancelled Courses")
    taking_place = n_("Courses Taking Place")

    def is_mergeable(self) -> bool:
        # All queries have only a single constraint.
        return True

    def test(self, event: models.Event, course: CdEDBObject, track_id: int) -> bool:  # pylint: disable=arguments-differ
        """Determine whether the course fits this stat for the given track."""
        if self == self.offered:
            return track_id in course['segments']
        elif self == self.cancelled:
            return (track_id in course['segments']
                    and track_id not in course['active_segments'])
        elif self == self.taking_place:
            return (track_id in course['segments']
                    and track_id in course['active_segments'])
        else:
            raise RuntimeError(n_("Impossible."))

    def _get_query_aux(self, event: models.Event, track_id: int) -> StatQueryAux:  # pylint: disable=arguments-differ
        # Track specific constraints need to be single-field so the relation between
        #  two constraints isn't spread across different fields for joined queries.
        if self == self.offered:
            return (
                [],
                [
                    (f"track{track_id}.is_offered", QueryOperators.equal, True),
                ],
                [],
            )
        elif self == self.cancelled:
            return (
                [f"track{t_id}.takes_place" for t_id in event.tracks]
                + [f"track{t_id}.is_cancelled" for t_id in event.tracks],
                [
                    (f"track{track_id}.is_cancelled", QueryOperators.equal, True),
                ],
                [],
            )
        elif self == self.taking_place:
            return (
                [],
                [
                    (f"track{track_id}.takes_place", QueryOperators.equal, True),
                ],
                [],
            )
        else:
            raise RuntimeError(n_("Impossible."))

    @staticmethod
    def _get_base_query(event: models.Event) -> Query:
        return Query(
            QueryScope.event_course,
            event.basic_course_query_spec,
            fields_of_interest=['course.nr', 'course.shortname', 'course.instructors'],
            constraints=[],
            order=[('course.nr', True)],
        )


@enum.unique
class EventRegistrationTrackStatistic(StatisticTrackMixin, enum.Enum):
    """This enum implements statistics for registration tracks."""

    def __new__(cls, value: str) -> "EventRegistrationTrackStatistic":
        obj = object.__new__(cls)
        obj._value_ = value
        obj.id_field = "reg.id"
        return obj

    all_instructors = n_("(Potential) Instructor")
    instructors = n_("Instructor")
    attendees = n_("Attendees")
    no_course = n_("No Course")

    def is_mergeable(self) -> bool:
        # Since all these queries are limited to participants, they all have
        #  correlations between constraints.
        return False

    def test(self, event: models.Event, reg: CdEDBObject, track_id: int) -> bool:  # pylint: disable=arguments-differ
        """Determine whether the registration fits this stat for the given track."""
        track = reg['tracks'][track_id]
        part = reg['parts'][event.tracks[track_id].part_id]

        # All checks require the registration to be a participant in the given track.
        if part['status'] != RPS.participant:
            return False

        if self == self.all_instructors:
            return track['course_instructor']
        elif self == self.instructors:
            return (track['course_id']
                    and track['course_id'] == track['course_instructor'])
        elif self == self.attendees:
            return (track['course_id']
                    and track['course_id'] != track['course_instructor'])
        elif self == self.no_course:
            return not track['course_id'] and reg['persona_id'] not in event.orgas
        else:
            raise RuntimeError(n_("Impossible."))

    def _get_query_aux(self, event: models.Event, track_id: int) -> StatQueryAux:  # pylint: disable=arguments-differ
        track = event.tracks[track_id]
        part = event.parts[track.part_id]
        if self == self.all_instructors:
            return (
                [f"track{track_id}.course_id", f"track{track_id}.course_instructor"],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.course_instructor",
                     QueryOperators.nonempty, None),
                ],
                [(f"course_instructor{track_id}.nr", True)],
            )
        elif self == self.instructors:
            return (
                [f"track{track_id}.course_instructor"],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.is_course_instructor",
                     QueryOperators.equal, True),
                ],
                [(f"course_instructor{track_id}.nr", True)],
            )
        elif self == self.attendees:
            return (
                [f"track{track_id}.course_id"],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.course_id", QueryOperators.nonempty, None),
                    (f"track{track_id}.is_course_instructor",
                     QueryOperators.equalornull, False),
                ],
                [(f"course{track_id}.nr", True)],
            )
        elif self == self.no_course:
            return (
                [],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.course_id", QueryOperators.empty, None),
                    ('persona.id', QueryOperators.otherthan, tuple(event.orgas)),
                ],
                [],
            )
        else:
            raise RuntimeError(n_("Impossible."))

    @staticmethod
    def _get_base_query(event: models.Event) -> Query:
        return Query(
            QueryScope.registration,
            event.basic_registration_query_spec,
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username'],
            constraints=[],
            order=[('persona.family_name', True), ('persona.given_names', True)],
        )


class EventRegistrationInXChoiceGrouper:
    """This class helps group registrations by their course choices for each track.

    Instantiating the `EventRegistrationInXChoiceGrouper` will create an internal
    dictionary storing the fitting registrations for each choice and track.

    Iterating over this class will provide a mapping of choice to number of fitting
    registrations, grouped by tracks, parts and part groups and sorted within each
    such group. For the table of the stats page each value contains all entries for
    the xth row, already presorted.
    """

    def __init__(self, event: models.Event, regs: CdEDBObjectMap):
        self._sorted_tracks = xsorted(event.tracks.values())
        self._sorted_parts = xsorted(event.parts.values())
        self._sorted_part_groups = xsorted(event.part_groups.values())
        self._max_choices = max(track.num_choices for track in self._sorted_tracks)
        self._track_ids_per_part = {
            int(part.id): set(part.tracks) for part in self._sorted_parts}
        self._track_ids_per_part_group = {
            int(part_group.id): set(itertools.chain.from_iterable(
                self._track_ids_per_part[part_id]
                for part_id in part_group.parts))
            for part_group in self._sorted_part_groups
        }

        self.choice_track_map: dict[int, dict[int, Optional[set[int]]]] = {
            x: {
                track.id: set() if track.num_choices > x else None
                for track in self._sorted_tracks
            }
            for x in range(self._max_choices)
        }

        # Put each registration into the appropriate choice pool for each track.
        for reg_id, reg in regs.items():
            for track in self._sorted_tracks:
                for x in range(track.num_choices):
                    if self._test(event, reg, track.id, x):
                        target = self.choice_track_map[x][track.id]
                        assert target is not None
                        target.add(reg_id)
                        break

    @staticmethod
    def _test(event: models.Event, reg: CdEDBObject, track_id: int, x: int) -> bool:
        """Uninlined helper to determine whether a reg fits choice x in a track."""
        course_track = event.tracks[track_id]
        event_part = event.parts[course_track.part_id]
        part = reg['parts'][event_part.id]
        track = reg['tracks'][track_id]
        return (_is_participant(part) and track['course_id']
                and len(track['choices']) > x
                and track['choices'][x] == track['course_id'])

    def _get_ids(self, x: int, track_ids: Collection[int]) -> Optional[set[int]]:
        """Uninlined helper to determine the number of fitting entries across tracks.

        If all given tracks do not offer an xth choice, return None, otherwise return
        the number of entries that fit the xth choice in any of the given tracks. This
        is easily done by unioning the values per track, but special care needs to be
        given to the None values.
        """
        result: Optional[set[int]] = None
        for track_id in track_ids:
            tmp = self.choice_track_map[x][track_id]
            if tmp is not None:
                if result is None:
                    result = set(tmp)
                else:
                    result |= tmp
        return result

    def __iter__(
            self,
    ) -> Iterator[tuple[int, dict[str, dict[int, Optional[set[int]]]]]]:
        """Iterate over all x choices, for each one return sorted counts by type."""
        # ret: dict[int, dict[str, dict[int, Optional[set[int]]]]] = {
        ret = {
            x: {
                'tracks': {
                    int(track.id): self._get_ids(x, (track.id,))
                    for track in self._sorted_tracks
                },
                'parts': {
                    part_id: self._get_ids(x, track_ids)
                    for part_id, track_ids in self._track_ids_per_part.items()
                },
                'part_groups': {
                    part_group_id: self._get_ids(x, track_ids)
                    for part_group_id, track_ids
                    in self._track_ids_per_part_group.items()
                },
            }
            for x in range(self._max_choices)
        }
        yield from ret.items()

    @staticmethod
    def _get_base_query(event: models.Event, reg_ids: Optional[Collection[int]],
                        ) -> Query:
        return Query(
            QueryScope.registration,
            event.basic_registration_query_spec,
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username'],
            constraints=[get_id_constraint('reg.id', reg_ids or ())],
            order=[('persona.family_name', True), ('persona.given_names', True)],
        )

    def get_query(self, event: models.Event, track_id: int, x: int) -> Query:
        query = self._get_base_query(event, self._get_ids(x, (track_id,)))
        query.fields_of_interest.append(f"track{track_id}.course_id")
        query.order = [(f"track{track_id}.course_id", True)] + query.order
        return query

    def get_query_part(self, event: models.Event, part_id: int, x: int) -> Query:
        track_ids = self._track_ids_per_part[part_id]
        query = self._get_base_query(event, self._get_ids(x, track_ids))
        query.fields_of_interest.extend(
            f"track{track_id}.course_id" for track_id in track_ids)
        return query

    def get_query_part_group(self, event: models.Event, part_group_id: int, x: int,
                             ) -> Query:
        track_ids = self._track_ids_per_part_group[part_group_id]
        query = self._get_base_query(event, self._get_ids(x, track_ids))
        query.fields_of_interest.extend(
            f"track{track_id}.course_id" for track_id in track_ids)
        return query

    @staticmethod
    def get_link_id(x: int, *, track_id: int = None, part_id: int = None,
                    part_group_id: int = None) -> str:
        if track_id:
            return f"track_in_{x}_choice_{track_id}"
        elif part_id:
            return f"part_in_{x}_choice_{part_id}"
        elif part_group_id:
            return f"part_group_in_{x}_choice_{part_group_id}"
        return ""


PART_STATISTICS = (EventRegistrationPartStatistic,)
TRACK_STATISTICS = (EventRegistrationTrackStatistic, EventCourseStatistic)
