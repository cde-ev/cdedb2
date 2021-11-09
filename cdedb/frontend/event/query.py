#!/usr/bin/env python3

"""
The `EventQueryMixin` subclasses the `EventBaseFrontend` and provides endpoints for
querying registrations, courses and lodgements.
"""

import collections
import datetime
import enum
import pprint
from typing import Dict, List, Optional, Tuple, Union

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    AgeClasses, CdEDBObject, CdEDBObjectMap, EntitySorter, RequestState, deduct_years,
    determine_age_class, n_, unwrap, xsorted,
)
from cdedb.frontend.common import (
    REQUESTdata, access, check_validation as check, event_guard,
    inspect_validation as inspect, periodic,
)
from cdedb.frontend.event.base import EventBaseFrontend
from cdedb.query import (
    Query, QueryConstraint, QueryOperators, QueryOrder, QueryScope,
    make_course_query_aux, make_lodgement_query_aux, make_registration_query_aux,
)

RPS = const.RegistrationPartStati

StatQueryAux = Tuple[List[str], List[QueryConstraint], List[QueryOrder]]


# Helper functions that are frequently used when testing stats.
def _is_participant(reg_part: CdEDBObject) -> bool:
    return reg_part['status'] == RPS.participant


# Helper functions to build query constraints frequently used by stats.
def _status_constraint(part: CdEDBObject, status: RPS, negate: bool = False
                       ) -> QueryConstraint:
    return (
        f"part{part['id']}.status",
        QueryOperators.unequal if negate else QueryOperators.equal,
        status.value
    )


def _participant_constraint(part: CdEDBObject) -> QueryConstraint:
    return _status_constraint(part, RPS.participant)


def _involved_constraint(part: CdEDBObject) -> QueryConstraint:
    return (f"part{part['id']}.status", QueryOperators.oneof,
            tuple(status.value for status in RPS if status.is_involved()))


def _present_constraint(part: CdEDBObject) -> QueryConstraint:
    return (f"part{part['id']}.status", QueryOperators.oneof,
            tuple(status.value for status in RPS if status.is_present()))


def _age_constraint(part: CdEDBObject, max_age: int, min_age: int = None
                    ) -> QueryConstraint:
    min_date = deduct_years(part['part_begin'], max_age)
    if min_age is None:
        return ('persona.birthday', QueryOperators.greater, min_date)
    else:
        # Add an offset of one, because `between` is inclusive on both ends.
        min_date += datetime.timedelta(days=1)
        max_date = deduct_years(part['part_begin'], min_age)
        return ('persona.birthday', QueryOperators.between, (min_date, max_date))


# Helper function to construct ordering for waitlist queries.
def _waitlist_order(event: CdEDBObject, part: CdEDBObject) -> List[QueryOrder]:
    ret = []
    if field_id := part['waitlist_field']:
        field_name = event['fields'][field_id]['field_name']
        ret.append((f'reg_fields.xfield_{field_name}', True))
    return ret + [('reg.payment', True), ('ctime.creation_time', True)]


# These enums each offer a collection of statistics for the stats page.
# They implement a test and query building interface:
# A `.test` method that takes the event data and a registrations, returning
# a bool indicating whether the given registration fits that statistic.
# A `.get_query` method that builds a `Query` object of the appropriate query scope
# that will show all fitting entities for that statistic.
# The enum member values are translatable strings to be used as labels for that
# statistic. The order of member definition inidicates the order they will be displayed.

class EventRegistrationPartStatistic(enum.Enum):
    """This enum implements statistics for registration parts.

    Some member names begin with an underscore, indicating, that they should be
    indented under the previous member without an underscore. This can be checked using
    the `.indent` property.
    """
    pending = n_("Open Registrations")
    _payed = n_("Paid")
    participant = n_("Participants")
    _minors = n_("All minors")
    _u18 = n_("U18")
    _u16 = n_("U16")
    _u14 = n_("U14")
    _checked_in = n_("Checked-In")
    _not_checked_in = n_("Not Checked-In")
    _orgas = n_("Orgas")
    waitlist = n_("Waitinglist")
    guest = n_("Guests")
    involved = n_("Total Active Registrations")
    _not_payed = n_("Not Paid")
    _no_parental_agreement = n_("Parental Consent Pending")
    present = n_("Present")
    _no_lodgement = n_("No Lodgement")
    cancelled = n_("Registration Cancelled")
    rejected = n_("Registration Rejected")
    total = n_("Total Registrations")

    @property
    def indent(self) -> bool:
        return self.name.startswith("_")

    def test(self, event: CdEDBObject, reg: CdEDBObject, part_id: CdEDBObject) -> bool:
        part = reg['parts'][part_id]
        if self == self.pending:
            return part['status'] == RPS.applied
        elif self == self._payed:
            return part['status'] == RPS.applied and reg['payment']
        elif self == self.participant:
            return _is_participant(part)
        elif self == self._minors:
            return _is_participant(part) and part['age_class'].is_minor()
        elif self == self._u18:
            return _is_participant(part) and part['age_class'] == AgeClasses.u18
        elif self == self._u16:
            return _is_participant(part) and part['age_class'] == AgeClasses.u16
        elif self == self._u14:
            return _is_participant(part) and part['age_class'] == AgeClasses.u14
        elif self == self._checked_in:
            return _is_participant(part) and reg['checkin']
        elif self == self._not_checked_in:
            return _is_participant(part) and not reg['checkin']
        elif self == self._orgas:
            return _is_participant(part) and reg['persona_id'] in event['orgas']
        elif self == self.waitlist:
            return part['status'] == RPS.waitlist
        elif self == self.guest:
            return part['status'] == RPS.guest
        elif self == self.involved:
            return part['status'].is_involved()
        elif self == self._not_payed:
            return part['status'].is_involved() and not reg['payment']
        elif self == self._no_parental_agreement:
            return (part['status'].is_involved() and part['age_class'].is_minor()
                    and not reg['parental_agreement'])
        elif self == self.present:
            return part['status'].is_present()
        elif self == self._no_lodgement:
            return part['status'].is_present() and not part['lodgement_id']
        elif self == self.cancelled:
            return part['status'] == RPS.cancelled
        elif self == self.rejected:
            return part['status'] == RPS.rejected
        elif self == self.total:
            return part['status'] != RPS.not_applied
        else:
            raise RuntimeError

    def _get_query_aux(self, event: CdEDBObject, part_id: int) -> StatQueryAux:
        part = event['parts'][part_id]
        if self == self.pending:
            return ([], [_status_constraint(part, RPS.applied)], [])
        elif self == self._payed:
            return (
                ['reg.payment'],
                [
                    _status_constraint(part, RPS.applied),
                    ('reg.payment', QueryOperators.nonempty, None),
                ],
                []
            )
        elif self == self.participant:
            return ([], [_participant_constraint(part)], [])
        elif self == self._minors:
            return (
                ['persona.birthday'],
                [_participant_constraint(part), _age_constraint(part, 18)],
                []
            )
        elif self == self._u18:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 18, 16),
                ],
                []
            )
        elif self == self._u16:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 16, 14),
                ],
                []
            )
        elif self == self._u14:
            return (
                ['persona.birthday'],
                [
                    _participant_constraint(part),
                    _age_constraint(part, 14),
                ],
                []
            )
        elif self == self._checked_in:
            return (
                ['reg.checkin'],
                [
                    _participant_constraint(part),
                    ('reg.checkin', QueryOperators.nonempty, None),
                ],
                []
            )
        elif self == self._not_checked_in:
            return (
                [],
                [
                    _participant_constraint(part),
                    ('reg.checkin', QueryOperators.empty, None),
                ],
                []
            )
        elif self == self._orgas:
            return (
                [],
                [
                    _participant_constraint(part),
                    ('persona.id', QueryOperators.oneof, tuple(event['orgas'])),
                ],
                []
            )
        elif self == self.waitlist:
            return (
                ['reg.payment', 'ctime.creation_time'],
                [_status_constraint(part, RPS.waitlist)],
                _waitlist_order(event, part)
            )
        elif self == self.guest:
            return ([], [_status_constraint(part, RPS.guest)], [])
        elif self == self.involved:
            return ([f"part{part['id']}.status"], [_involved_constraint(part)], [])
        elif self == self._not_payed:
            return (
                [f"part{part['id']}.status"],
                [
                    _involved_constraint(part),
                    ('reg.payment', QueryOperators.empty, None),
                ],
                []
            )
        elif self == self._no_parental_agreement:
            return (
                [f"part{part['id']}.status"],
                [
                    _involved_constraint(part),
                    _age_constraint(part, 18),
                    ('reg.parental_agreement', QueryOperators.equal, False),
                ],
                []
            )
        elif self == self.present:
            return ([f"part{part['id']}.status"], [_present_constraint(part)], [])
        elif self == self._no_lodgement:
            return (
                [f"part{part['id']}.status"],
                [
                    _present_constraint(part),
                    (f"part{part['id']}.lodgement_id", QueryOperators.empty, None),
                ],
                []
            )
        elif self == self.cancelled:
            return (
                ['reg.amount_paid'],
                [_status_constraint(part, RPS.cancelled)],
                []
            )
        elif self == self.rejected:
            return (
                ['reg.amount_paid'],
                [_status_constraint(part, RPS.rejected)],
                []
            )
        elif self == self.total:
            return (
                [f"part{part['id']}.status"],
                [_status_constraint(part, RPS.not_applied, negate=True)],
                []
            )
        else:
            raise RuntimeError

    def get_query(self, event: CdEDBObject, part_id: int) -> Query:
        query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username'],
            constraints=[],
            order=[('persona.family_name', True), ('persona.given_names', True)]
        )
        fields, constraints, order = self._get_query_aux(event, part_id)
        query.fields_of_interest.extend(fields)
        query.constraints.extend(constraints)
        # Prepend the specific order.
        query.order = order + query.order
        return query


class EventCourseStatistic(enum.Enum):
    """This enum implements statistics for courses in course tracks."""
    offered = n_("Course Offers")
    cancelled = n_("Cancelled Courses")

    def test(self, course: CdEDBObject, track_id: int) -> bool:
        if self == self.offered:
            return track_id in course['segments']
        elif self == self.cancelled:
            return (track_id in course['segments']
                    and track_id not in course['active_segments'])
        else:
            raise RuntimeError

    def _get_query_aux(self, track_id: int) -> StatQueryAux:
        if self == self.offered:
            return (
                ['course.instructors'],
                [(f"track{track_id}.is_offered", QueryOperators.equal, True)],
                []
            )
        elif self == self.cancelled:
            return (
                ['course.instructors'],
                [
                    (f"track{track_id}.is_offered", QueryOperators.equal, True),
                    (f"track{track_id}.takes_place", QueryOperators.equal, False),
                ],
                []
            )
        else:
            raise RuntimeError

    def get_query(self, event: CdEDBObject, track_id: int) -> Query:
        query = Query(
            QueryScope.event_course,
            QueryScope.event_course.get_spec(event=event),
            fields_of_interest=['course.course_id'],
            constraints=[],
            order=[('course.nr', True)]
        )
        fields, constraints, order = self._get_query_aux(track_id)
        query.fields_of_interest.extend(fields)
        query.constraints.extend(constraints)
        # Prepend the specific order.
        query.order = order + query.order
        return query


class EventRegistrationTrackStatistic(enum.Enum):
    """This enum implements statistics for registration tracks."""
    all_instructors = n_("(Potential) Instructor")
    instructors = n_("Instructor")
    attendees = n_("Attendees")
    no_course = n_("No Course")

    def test(self, event: CdEDBObject, reg: CdEDBObject, track_id: int) -> bool:
        track = reg['tracks'][track_id]
        part = reg['parts'][event['tracks'][track_id]['part_id']]

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
            return not track['course_id'] and reg['persona_id'] not in event['orgas']
        else:
            raise RuntimeError

    def _get_query_aux(self, event: CdEDBObject, track_id: int) -> StatQueryAux:
        track = event['tracks'][track_id]
        part = event['parts'][track['part_id']]
        if self == self.all_instructors:
            return (
                [f"track{track_id}.course_id", f"track{track_id}.course_instructor"],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.course_instructor",
                     QueryOperators.nonempty, None),
                ],
                [(f"course_instructor{track_id}.nr", True)]
            )
        elif self == self.instructors:
            return (
                [f"track{track_id}.course_instructor"],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.is_course_instructor",
                     QueryOperators.equal, True),
                ],
                [(f"course_instructor{track_id}.nr", True)]
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
                [(f"course{track_id}.nr", True)]
            )
        elif self == self.no_course:
            return (
                [],
                [
                    _participant_constraint(part),
                    (f"track{track_id}.course_id", QueryOperators.empty, None),
                    ('persona.id', QueryOperators.otherthan, event['orgas']),
                ],
                []
            )
        else:
            raise RuntimeError

    def get_query(self, event: CdEDBObject, track_id: int) -> Query:
        query = Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username'],
            constraints=[],
            order=[('persona.family_name', True), ('persona.given_names', True)]
        )
        fields, constraints, order = self._get_query_aux(event, track_id)
        query.fields_of_interest.extend(fields)
        query.constraints.extend(constraints)
        # Prepend the specific order.
        query.order = order + query.order
        return query


class EventRegistrationInXChoiceGrouper:
    """This class helps group registrations by their course choices for each track.

    Instantiating the `EventRegistrationInXChoiceGrouper` will populate a dictionary
    accessible via the `choice_track_map` attribute, mapping choice rank to a mapping
    of track id to list of regisration ids.

    Iterating over the outer mapping will yield ranks and row data to be displayed on
    the stats page.
    """
    def __init__(self, event: CdEDBObject, regs: CdEDBObjectMap):
        tracks = event['tracks']
        max_choices = max(track['num_choices'] for track in tracks.values())
        self.choice_track_map: Dict[int, Dict[int, Optional[List[int]]]] = {
            x: {
                track_id: [] if track['num_choices'] > x else None
                for track_id, track in tracks.items()
            }
            for x in range(max_choices)
        }

        for reg_id, reg in regs.items():
            for track_id, track in tracks.items():
                for x in range(track['num_choices']):
                    if self.test(event, reg, track_id, x):
                        target = self.choice_track_map[x][track_id]
                        assert target is not None
                        target.append(reg_id)
                        break

    @staticmethod
    def test(event: CdEDBObject, reg: CdEDBObject, track_id: int, x: int) -> bool:
        course_track = event['tracks'][track_id]
        event_part = event['parts'][course_track['part_id']]
        part = reg['parts'][event_part['id']]
        track = reg['tracks'][track_id]
        return (_is_participant(part) and track['course_id']
                and len(track['choices']) > x
                and track['choices'][x] == track['course_id'])

    def get_query(self, event: CdEDBObject, track_id: int, x: int) -> Query:
        return Query(
            QueryScope.registration,
            QueryScope.registration.get_spec(event=event),
            fields_of_interest=['reg.id', 'persona.given_names', 'persona.family_name',
                                'persona.username', f"track{track_id}.course_id"],
            constraints=[
                ('reg.id', QueryOperators.oneof, self.choice_track_map[x][track_id]),
            ],
            order=[(f"course{track_id}.nr", True), ('persona.family_name', True),
                   ('persona.given_names', True)]
        )


class EventQueryMixin(EventBaseFrontend):
    @access("event")
    @event_guard()
    def stats(self, rs: RequestState, event_id: int) -> Response:
        """Present an overview of the basic stats."""
        event_parts = rs.ambience['event']['parts']
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        # Precompute age classes of participants for all registration parts.
        for reg in registrations.values():
            for part_id, reg_part in reg['parts'].items():
                reg_part['age_class'] = determine_age_class(
                    personas[reg['persona_id']]['birthday'],
                    event_parts[part_id]['part_begin'])

        per_part_statistics: Dict[EventRegistrationPartStatistic, Dict[int, int]]
        per_part_statistics = collections.OrderedDict()
        for reg_stat in EventRegistrationPartStatistic:
            per_part_statistics[reg_stat] = {
                part_id: sum(
                    1 for reg in registrations.values()
                    if reg_stat.test(rs.ambience['event'], reg, part_id))
                for part_id in event_parts
            }

        per_track_statistics: Dict[
            Union[EventRegistrationTrackStatistic, EventCourseStatistic],
            Dict[int, int]]
        per_track_statistics = collections.OrderedDict()
        grouper = None
        if tracks:
            for course_stat in EventCourseStatistic:
                per_track_statistics[course_stat] = {
                    track_id: sum(
                        1 for course in courses.values()
                        if course_stat.test(course, track_id))
                    for track_id in tracks
                }
            for reg_track_stat in EventRegistrationTrackStatistic:
                per_track_statistics[reg_track_stat] = {
                    track_id: sum(
                        1 for reg in registrations.values()
                        if reg_track_stat.test(rs.ambience['event'], reg, track_id))
                    for track_id in tracks
                }

            grouper = EventRegistrationInXChoiceGrouper(
                rs.ambience['event'], registrations)

        return self.render(rs, "query/stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_track_statistics': per_track_statistics, 'grouper': grouper,
        })

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def registration_query(self, rs: RequestState, event_id: int,
                           download: Optional[str], is_search: bool,
                           ) -> Response:
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        scope = QueryScope.registration
        spec = scope.get_spec(event=rs.ambience["event"])
        # mangle the input, so we can prefill the form
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)
        choices, titles = make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements, lodgement_groups,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = self.conf["DEFAULT_QUERIES_REGISTRATION"](
            rs.gettext, rs.ambience['event'], spec)
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "registration_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/registration_query", params)

    @access("event", modi={"POST"}, anti_csrf_token_name="store_query")
    @event_guard()
    @REQUESTdata("query_name", "query_scope")
    def store_event_query(self, rs: RequestState, event_id: int, query_name: str,
                          query_scope: QueryScope) -> Response:
        """Store an event query."""
        if not query_scope or not query_scope.get_target():
            rs.ignore_validation_errors()
            return self.redirect(rs, "event/show_event")
        if rs.has_validation_errors() or not query_name:
            rs.notify("error", n_("Invalid query name."))

        spec = query_scope.get_spec(event=rs.ambience["event"])
        query_input = query_scope.mangle_query_input(rs)
        query_input["is_search"] = "True"
        query: Optional[Query] = check(
            rs, vtypes.QueryInput, query_input, "query", spec=spec, allow_empty=False)
        if not rs.has_validation_errors() and query:
            query_id = self.eventproxy.store_event_query(
                rs, rs.ambience["event"]["id"], query)
            self.notify_return_code(rs, query_id)
            if query_id:
                query.query_id = query_id
                del query_input["query_name"]
        return self.redirect(rs, query_scope.get_target(), query_input)

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdata("query_id", "query_scope")
    def delete_event_query(self, rs: RequestState, event_id: int,
                           query_id: int, query_scope: QueryScope) -> Response:
        """Delete a stored event query."""
        query_input = None
        if not rs.has_validation_errors():
            stored_query = unwrap(
                self.eventproxy.get_event_queries(rs, event_id, query_ids=(query_id,))
                or None)
            if stored_query:
                query_input = stored_query.serialize()
            code = self.eventproxy.delete_event_query(rs, query_id)
            self.notify_return_code(rs, code)
        if query_scope and query_scope.get_target():
            return self.redirect(rs, query_scope.get_target(), query_input)
        return self.redirect(rs, "event/show_event", query_input)

    @periodic("validate_stored_event_queries", 4 * 24)
    def validate_stored_event_queries(self, rs: RequestState, state: CdEDBObject
                                      ) -> CdEDBObject:
        """Validate all stored event queries, to ensure nothing went wrong."""
        data = {}
        event_ids = self.eventproxy.list_events(rs, archived=False)
        for event_id in event_ids:
            data.update(self.eventproxy.get_invalid_stored_event_queries(rs, event_id))
        text = "Liebes Datenbankteam, einige gespeicherte Event-Queries sind ungültig:"
        if data:
            pdata = pprint.pformat(data)
            self.logger.warning(f"Invalid stroed event queries: {pdata}")
            msg = self._create_mail(f"{text}\n{pdata}",
                                    {"To": ("cdedb@lists.cde-ev.de",),
                                     "Subject": "Ungültige Event-Queries"},
                                    attachments=None)
            self._send_mail(msg)
        return state

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def course_query(self, rs: RequestState, event_id: int,
                     download: Optional[str], is_search: bool,
                     ) -> Response:

        scope = QueryScope.event_course
        spec = scope.get_spec(event=rs.ambience['event'])
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput, query_input,
                          "query", spec=spec, allow_empty=False)

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        choices, titles = make_course_query_aux(
            rs, rs.ambience['event'], courses,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        tracks = rs.ambience['event']['tracks']
        selection_default = ["course.shortname", ]
        for col in ("is_offered", "takes_place", "attendees"):
            selection_default += list("track{}.{}".format(t_id, col)
                                      for t_id in tracks)
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries = self.conf["DEFAULT_QUERIES_COURSE"](
            rs.gettext, rs.ambience['event'], spec)
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "course_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/course_query", params)

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def lodgement_query(self, rs: RequestState, event_id: int,
                        download: Optional[str], is_search: bool,
                        ) -> Response:

        scope = QueryScope.lodgement
        spec = scope.get_spec(event=rs.ambience["event"])
        query_input = scope.mangle_query_input(rs)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                          query_input, "query", spec=spec, allow_empty=False)

        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(
            rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(
            rs, lodgement_group_ids)
        choices, titles = make_lodgement_query_aux(
            rs, rs.ambience['event'], lodgements, lodgement_groups,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        parts = rs.ambience['event']['parts']
        selection_default = ["lodgement.title"] + [
            f"lodgement_fields.xfield_{field['field_name']}"
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement]
        for col in ("regular_inhabitants",):
            selection_default += list(f"part{p_id}_{col}" for p_id in parts)

        default_queries = {}
        stored_queries = self.eventproxy.get_event_queries(
            rs, event_id, scopes=(scope,))
        default_queries.update(stored_queries)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries, 'titles': titles,
            'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "lodgement_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "query/lodgement_query", params)

    def _send_query_result(self, rs: RequestState, download: Optional[str],
                           filename: str, scope: QueryScope, query: Query,
                           params: CdEDBObject) -> Response:
        if download:
            shortname = rs.ambience['event']['shortname']
            return self.send_query_download(
                rs, params['result'], query.fields_of_interest, kind=download,
                filename=f"{shortname}_{filename}",
                substitutions=params['choices'])
        else:
            return self.render(rs, scope.get_target(redirect=False), params)

    @access("event")
    @REQUESTdata("phrase", "kind", "aux")
    def select_registration(self, rs: RequestState, phrase: str,
                            kind: str, aux: Optional[vtypes.ID]) -> Response:
        """Provide data for inteligent input fields.

        This searches for registrations (and associated users) by name
        so they can be easily selected without entering their
        numerical ids. This is similar to the select_persona()
        functionality in the core realm.

        The kind parameter specifies the purpose of the query which
        decides the privilege level required and the basic search
        paramaters.

        Allowed kinds:

        - ``orga_registration``: Search for a registration as event orga

        The aux parameter allows to supply an additional id. This will
        probably be an event id in the overwhelming majority of cases.

        Required aux value based on the 'kind':

        * ``orga_registration``: Id of the event you are orga of
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})

        spec_additions: Dict[str, str] = {}
        search_additions: List[QueryConstraint] = []
        event = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin", "meta_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "orga_registration":
            if aux is None:
                return self.send_json(rs, {})
            event = self.eventproxy.get_event(rs, aux)
            if not self.is_admin(rs):
                if rs.user.persona_id not in event['orgas']:
                    raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        else:
            return self.send_json(rs, {})

        data = None

        anid, errs = inspect(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            tmp = self.eventproxy.get_registrations(rs, (anid,))
            if tmp:
                reg = unwrap(tmp)
                if reg['event_id'] == aux:
                    data = [reg]

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf["NUM_PREVIEW_CHARS"]:
            return self.send_json(rs, {})

        terms: List[str] = []
        if data is None:
            terms = [t.strip() for t in phrase.split(' ') if t]
            valid = True
            for t in terms:
                _, errs = inspect(vtypes.NonRegex, t, argname="phrase")
                if errs:
                    valid = False
            if not valid:
                data = []
            else:
                search = [("username,family_name,given_names,display_name",
                           QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = QueryScope.quick_registration.get_spec()
                spec["username,family_name,given_names,display_name"] = "str"
                spec.update(spec_additions)
                query = Query(
                    QueryScope.quick_registration, spec,
                    ("registrations.id", "username", "family_name",
                     "given_names", "display_name"),
                    search, (("registrations.id", True),))
                data = list(self.eventproxy.submit_general_query(
                    rs, query, event_id=aux))

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            data = xsorted(data, key=lambda e: e['id'])[:num_preview_personas]

        def name(x: CdEDBObject) -> str:
            return "{} {}".format(x['given_names'], x['family_name'])

        # Check if name occurs multiple times to add email address in this case
        counter: Dict[str, int] = collections.defaultdict(int)
        for entry in data:
            counter[name(entry)] += 1

        # Generate return JSON list
        ret = []
        for entry in xsorted(data, key=EntitySorter.persona):
            result = {
                'id': entry['id'],
                'name': name(entry),
                'display_name': entry['display_name'],
            }
            # Email/username is only delivered if we have admins
            # rights, a search term with an @ (and more) matches the
            # mail address, or the mail address is required to
            # distinguish equally named users
            searched_email = any(
                '@' in t and len(t) > self.conf["NUM_PREVIEW_CHARS"]
                and entry['username'] and t in entry['username']
                for t in terms)
            if (counter[name(entry)] > 1 or searched_email or
                    self.is_admin(rs)):
                result['email'] = entry['username']
            ret.append(result)
        return self.send_json(rs, {'registrations': ret})
