#!/usr/bin/env python3

"""
The `EventRegistrationBackend` subclasses the `EventBaseBackend` and provides
functionality for managing registrations belonging to an event, including managing the
waitlist, calculating and booking event fees and checking the status of multiple
registrations at once for the mailinglist realm.
"""
import copy
import dataclasses
import datetime
import decimal
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from typing import Any, NamedTuple, Optional, Protocol, TypeVar

import psycopg2.extensions

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.fee_condition_parser.evaluation as fcp_evaluation
import cdedb.fee_condition_parser.parsing as fcp_parsing
import cdedb.fee_condition_parser.roundtrip as fcp_roundtrip
import cdedb.models.event as models
from cdedb.backend.common import (
    access, affirm_array_validation as affirm_array,
    affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, internal, singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    PARSE_OUTPUT_DATEFORMAT, CdEDBObject, CdEDBObjectMap, CourseFilterPositions,
    DefaultReturnCode, DeletionBlockers, InfiniteEnum, PsycoJson, RequestState,
    cast_fields, glue, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import (
    REGISTRATION_FIELDS, REGISTRATION_PART_FIELDS, REGISTRATION_TRACK_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.filter import date_filter, money_filter

T = TypeVar("T")


class CourseChoiceValidationAux(NamedTuple):
    course_segments: Mapping[int, set[int]]
    synced_tracks: Mapping[int, set[int]]
    involved_tracks: set[int]
    orga_input: bool


FeeStats = dict[str, dict[const.EventFeeType, decimal.Decimal]]


@dataclasses.dataclass
class RegistrationFee:
    amount: decimal.Decimal
    active_fees: set[vtypes.ProtoID]
    visual_debug: dict[int, str]
    by_kind: dict[const.EventFeeType, decimal.Decimal]


@dataclasses.dataclass
class RegistrationFeeData:
    member_fee: RegistrationFee
    nonmember_fee: RegistrationFee
    is_member: bool

    @property
    def fee(self) -> RegistrationFee:
        return self.member_fee if self.is_member else self.nonmember_fee

    @property
    def amount(self) -> decimal.Decimal:
        return self.fee.amount

    @property
    def donation(self) -> decimal.Decimal:
        return self.fee.by_kind[const.EventFeeType.donation]

    @property
    def nonmember_surcharge_amount(self) -> decimal.Decimal:
        return self.nonmember_fee.amount - self.member_fee.amount

    @property
    def nonmember_surcharge(self) -> bool:
        return not self.is_member and self.nonmember_surcharge_amount > 0


class EventRegistrationBackend(EventBaseBackend):
    def _get_course_segments_per_course(self, rs: RequestState,
                                        event_id: int) -> dict[int, set[int]]:
        """
        Helper function to get course segments of all courses of an event.

        Required for _set_course_choices(). This should be called outside of looping
        over tracks and/or registrations, to avoid having to query the same information
        multiple times.

        :returns: A dict mapping each course id (of the event) to a set of
            track ids (which correspond to its segments)
        """
        query = """
            SELECT courses.id, array_agg(segments.track_id) AS segments
            FROM (
                event.courses AS courses
                LEFT OUTER JOIN event.course_segments AS segments
                ON courses.id = segments.course_id
            )
            WHERE courses.event_id = %s
            GROUP BY courses.id"""

        return {row['id']: set(row['segments'])
                for row in self.query_all(rs, query, (event_id,))}

    def _get_involved_tracks(self, rs: RequestState, registration_id: int,
                             ) -> set[int]:
        """Return the track ids of all tracks the registration is involved with."""
        q = """
            SELECT course_tracks.id
            FROM event.course_tracks
            WHERE course_tracks.part_id IN (
                SELECT part_id FROM event.registration_parts
                WHERE registration_id = %s AND status = ANY(%s)
            )
        """
        p = (registration_id,
             [x for x in const.RegistrationPartStati if x.is_involved()])
        return {e['id'] for e in self.query_all(rs, q, p)}

    def _get_synced_tracks(self, rs: RequestState, event_id: int,
                           ) -> dict[int, set[int]]:
        """Return a mapping of track id to ids of tracks synced to that track.

        The value will be an empty set for unsynced tracks.
        """
        q = """
            SELECT ct.id, COALESCE(synced_tracks, ARRAY[]::integer[]) AS synced_tracks
            FROM event.course_tracks AS ct
            JOIN event.event_parts AS ep on ep.id = ct.part_id
            LEFT JOIN (
                SELECT ct.id, ARRAY_AGG(tgt2.track_id) AS synced_tracks
                FROM event.course_tracks AS ct
                LEFT JOIN event.track_group_tracks AS tgt ON ct.id = tgt.track_id
                LEFT JOIN event.track_groups AS tg ON tgt.track_group_id = tg.id
                LEFT JOIN event.track_group_tracks AS tgt2 on tg.id = tgt2.track_group_id
                WHERE tg.constraint_type = %s AND tg.event_id = %s
                GROUP BY ct.id
            ) AS tmp ON tmp.id = ct.id
            WHERE ep.event_id = %s
        """
        p = (const.CourseTrackGroupType.course_choice_sync, event_id, event_id)
        return {e['id']: set(e['synced_tracks']) for e in self.query_all(rs, q, p)}

    @access("event")
    def get_course_choice_validation_aux(self, rs: RequestState, event_id: int,
                                         registration_id: Optional[int],
                                         orga_input: bool,
                                         part_ids: Optional[Collection[int]] = None,
                                         ) -> CourseChoiceValidationAux:
        """Gather auxilliary data necessary to validate course choices.

        This retrieves three datapoints:
          * course_segments: Which course is offered in which tracks.
          * synced_tracks: To which tracks each track is synced to.
          * involved_tracks: Which tracks a registration is involved with.

        The return of this method can be passed to `validate_single_course_choice`.
        Since that is called in a loop, this should only be called once.

        To determine involved tracks, a registration id can be given, which will then
        be used to read this information from the database, or the involved parts can
        be passed directly in case that data is not available in the database yet,
        for example during validation before creating a new registration.
        """
        event_id = affirm(vtypes.ID, event_id)
        registration_id = affirm_optional(vtypes.ID, registration_id)
        part_ids = affirm_set(vtypes.ID, part_ids or ())
        if registration_id:
            involved_tracks = self._get_involved_tracks(rs, registration_id)
        elif part_ids:
            q = """
                SELECT ct.id
                FROM event.course_tracks AS ct
                    JOIN event.event_parts AS ep on ep.id = ct.part_id
                WHERE ep.id = ANY(%s)
            """
            involved_tracks = {e['id'] for e in self.query_all(rs, q, (part_ids,))}
        else:
            # For multiedit, we cannot reliably determine part ids, but we don't need
            #  them either, so not returning anything does not hurt.
            involved_tracks = set()
        return CourseChoiceValidationAux(
            self._get_course_segments_per_course(rs, event_id),
            self._get_synced_tracks(rs, event_id),
            involved_tracks=involved_tracks,
            orga_input=orga_input,
        )

    @access("event")
    def validate_single_course_choice(self, rs: RequestState, course_id: int,  # pylint: disable=no-self-use
                                      track_id: int, aux: CourseChoiceValidationAux,
                                      ) -> bool:
        """Check whether a course choice is allowed in a given track.

        Returns True for valid choice and False for invalid choice.

        :param aux: As returned by `get_course_choice_validation_aux`. This is
            dependent on the event and a specific registration.
        """
        course_id = affirm(vtypes.ID, course_id)
        track_id = affirm(vtypes.ID, track_id)
        # Either the course is offered in this track.
        if track_id in (offered_tracks := aux.course_segments.get(course_id, set())):
            return True
        # Or the course is offered in a synced track, that we are involved with.
        if aux.synced_tracks[track_id] & aux.involved_tracks & offered_tracks:
            return True
        # If this is an orga operation, ignore involvement.
        if aux.orga_input and aux.synced_tracks[track_id] & offered_tracks:
            return True
        # Otherwise the choice is not allowed.
        return False

    @access("event")
    def get_course_segments_per_track(self, rs: RequestState, event_id: int,
                                      active_only: bool = False,
                                      ) -> dict[int, set[int]]:
        """Determine which courses can be chosen in each track.

        :param active_only: If True, restrict to active course segments, i.e. courses
            that are taking place.
        :returns: A map of <track id> -> [<course_id>, ...], indicating that these
            courses can be chosen in the given track.
        """
        query = """
            SELECT ct.id, ARRAY_REMOVE(ARRAY_AGG(cs.course_id), NULL) AS courses
            FROM (
                event.course_tracks AS ct
                LEFT JOIN event.event_parts AS ep ON ct.part_id = ep.id
                LEFT JOIN event.course_segments AS cs ON ct.id = cs.track_id {}
            )
            WHERE ep.event_id = %s
            GROUP BY ct.id
        """

        event_id = affirm(vtypes.ID, event_id)
        active_only = affirm(bool, active_only)
        query = query.format("AND is_active = True" if active_only else "")

        return {
            e['id']: set(e['courses'])
            for e in self.query_all(rs, query, (event_id,))
        }

    @access("event")
    def get_course_segments_per_track_group(
            self, rs: RequestState, event_id: int, active_only: bool = False,
            involved_parts: Optional[Collection[int]] = None,
    ) -> dict[int, set[int]]:
        """Determine which courses can be chosen in each track group.

        :param active_only: If True, restrict to active course segments, i.e. courses
            that are taking place.
        :returns: A map of <track id> -> [<course_id>, ...], indicating that these
            courses can be chosen in the given track.
        """
        query = """
            SELECT tg.id, ARRAY_REMOVE(ARRAY_AGG(DISTINCT cs.course_id), NULL) AS courses
            FROM event.track_groups AS tg
                LEFT JOIN event.track_group_tracks AS tgt ON tg.id = tgt.track_group_id
                LEFT JOIN event.course_segments AS cs ON tgt.track_id = cs.track_id {is_active}
                LEFT JOIN event.course_tracks AS ct ON cs.track_id = ct.id {involved_parts}
            WHERE tg.event_id = %s AND tg.constraint_type = %s
            GROUP BY tg.id
        """

        event_id = affirm(vtypes.ID, event_id)
        active_only = affirm(bool, active_only)

        params: list[Any] = []

        if involved_parts is not None:
            involved_parts = affirm_set(vtypes.ID, involved_parts)
            params.append(involved_parts)

        query = query.format(
            is_active="AND is_active = True" if active_only else "",
            involved_parts=(
                "AND ct.part_id = ANY(%s)" if involved_parts is not None else ""),
        )
        params.extend((event_id, const.CourseTrackGroupType.course_choice_sync))

        return {
            e['id']: set(e['courses'])
            for e in self.query_all(rs, query, params)
        }

    def _set_course_choices(self, rs: RequestState, registration_id: int,
                            track_id: int, choices: Optional[Sequence[int]],
                            aux: CourseChoiceValidationAux,
                            new_registration: bool = False,
                            ) -> DefaultReturnCode:
        """Helper for handling of course choices.

        Used when setting or creating registrations.

        :note: This has to be called inside an atomized context.

        :param aux: Additional data, as returned by `get_course_choice_validation_aux`.
        :param new_registration: Performance optimization for creating
            registrations: If true, the deletion of existing choices is skipped.
        """
        ret = 1
        self.affirm_atomized_context(rs)
        if choices is None:
            # Nothing specified, hence nothing to do
            return ret
        for course_id in choices:
            if not self.validate_single_course_choice(rs, course_id, track_id, aux):
                raise ValueError(n_("Wrong track for course."))
        if not new_registration:
            query = ("DELETE FROM event.course_choices"
                     " WHERE registration_id = %s AND track_id = %s")
            self.query_exec(rs, query, (registration_id, track_id))
        for rank, course_id in enumerate(choices):
            new_choice = {
                "registration_id": registration_id,
                "track_id": track_id,
                "course_id": course_id,
                "rank": rank,
            }
            ret *= self.sql_insert(rs, "event.course_choices", new_choice)
        return ret

    def _get_registration_info(self, rs: RequestState,
                               reg_id: int) -> Optional[CdEDBObject]:
        """Helper to retrieve basic registration information."""
        return self.sql_select_one(
            rs, "event.registrations", ("persona_id", "event_id"), reg_id)

    @access("event")
    def list_persona_registrations(
        self, rs: RequestState, persona_id: int,
    ) -> dict[int, dict[int, dict[int, const.RegistrationPartStati]]]:
        """List all events a given user has a registration for.

        :returns: Mapping of event ids to
            (registration id to (part id to registration status))
        """
        if not (self.is_admin(rs) or self.core.is_relative_admin(rs, persona_id)
                or rs.user.persona_id == persona_id):
            raise PrivilegeError(n_("Not privileged."))
        persona_id = affirm(vtypes.ID, persona_id)

        query = ("SELECT event_id, registration_id, part_id, status"
                 " FROM event.registrations"
                 " LEFT JOIN event.registration_parts"
                 " ON registrations.id = registration_parts.registration_id"
                 " WHERE persona_id = %s")
        data = self.query_all(rs, query, (persona_id,))
        ret: dict[int, dict[int, dict[int, const.RegistrationPartStati]]] = {}
        for e in data:
            ret.setdefault(
                e['event_id'], {},
            ).setdefault(
                e['registration_id'], {},
            )[e['part_id']] = const.RegistrationPartStati(e['status'])
        return ret

    @access("event", "ml_admin")
    def list_registrations_personas(self, rs: RequestState, event_id: int,
                                    persona_ids: Optional[Collection[int]] = None,
                                    ) -> dict[int, int]:
        """List all registrations of an event.

        :param persona_ids: If passed restrict to registrations by these personas.
        :returns: Mapping of registration ids to persona_ids.
        """
        if not persona_ids:
            persona_ids = set()
        event_id = affirm(vtypes.ID, event_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        # ml_admins are allowed to do this to be able to manage
        # subscribers of event mailinglists.
        # finance_admins are allowed here to book event fees.
        if (persona_ids != {rs.user.persona_id}
                and not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)
                and {"ml_admin", "finance_admin"}.isdisjoint(rs.user.roles)):
            raise PrivilegeError(n_("Not privileged."))

        query = "SELECT id, persona_id FROM event.registrations"
        conditions = ["event_id = %s"]
        params: list[Any] = [event_id]
        if persona_ids:
            conditions.append("persona_id = ANY(%s)")
            params.append(persona_ids)
        query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event", "ml_admin")
    def list_registrations(self, rs: RequestState, event_id: int,
                           persona_id: Optional[int] = None) -> dict[int, int]:
        """Manual singularization of list_registrations_personas

        Handles default values properly.
        """
        if persona_id:
            return self.list_registrations_personas(rs, event_id, {persona_id})
        else:
            return self.list_registrations_personas(rs, event_id)

    @access("event")
    def list_participants(self, rs: RequestState, event_id: int) -> dict[int, int]:
        """List all participants of an event.

        Just participants of this event are returned and the requester himself must
        have the status 'participant'.

        :returns: Mapping of registration ids to persona_ids.
        """
        event_id = affirm(vtypes.ID, event_id)

        # In this case, privilege check is performed afterwards since it depends on
        # the result of the query.
        query = """SELECT DISTINCT
            regs.id, regs.persona_id
        FROM
            event.registrations AS regs
            LEFT OUTER JOIN
                event.registration_parts AS rparts
            ON rparts.registration_id = regs.id"""
        conditions = ["regs.event_id = %s", "rparts.status = %s"]
        params = [event_id, const.RegistrationPartStati.participant]
        query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e['persona_id'] for e in data}

        if not (rs.user.persona_id in ret.values()
                or self.is_orga(rs, event_id=event_id)
                or self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        return ret

    @access("persona")
    def check_registrations_status(
            self, rs: RequestState, persona_ids: Collection[int], event_id: int,
            stati: Collection[const.RegistrationPartStati]) -> dict[int, bool]:
        """Check if any status for a given event matches one of the given stati.

        This is mostly used to determine mailinglist eligibility. Thus,
        ml_admins are allowed to do this to manage subscribers.

        A user may do this for themselves, an orga for their event and an
        event or ml admin for every user.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        event_id = affirm(vtypes.ID, event_id)
        stati = affirm_set(const.RegistrationPartStati, stati)

        # By default, assume no participation.
        ret = {anid: False for anid in persona_ids}

        # First, rule out people who can not participate at any event.
        if (persona_ids == {rs.user.persona_id} and
                "event" not in rs.user.roles):
            return ret

        # Check if eligible to check registration status for other users.
        if not (persona_ids == {rs.user.persona_id}
                or self.is_orga(rs, event_id=event_id)
                or self.is_admin(rs)
                or "ml_admin" in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))

        registration_ids = self.list_registrations_personas(rs, event_id, persona_ids)
        if not registration_ids:
            return {anid: False for anid in persona_ids}

        registrations = self.get_registrations(rs, registration_ids)
        ret.update({reg['persona_id']:
                        any(part['status'] in stati for part in reg['parts'].values())
                    for reg in registrations.values()})
        return ret

    class _GetRegistrationStatusProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int, event_id: int,
                     stati: Collection[const.RegistrationPartStati]) -> bool: ...
    check_registration_status: _GetRegistrationStatusProtocol = singularize(
        check_registrations_status, "persona_ids", "persona_id")

    @access("event")
    def get_registration_map(self, rs: RequestState, event_ids: Collection[int],
                             ) -> dict[tuple[int, int], int]:
        """Retrieve a map of personas to their registrations."""
        event_ids = affirm_set(vtypes.ID, event_ids)
        if (not all(self.is_orga(rs, event_id=anid) for anid in event_ids) and
                not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))

        data = self.sql_select(
            rs, "event.registrations", ("id", "persona_id", "event_id"),
            event_ids, entity_key="event_id")
        ret = {(e["event_id"], e["persona_id"]): e["id"] for e in data}

        return ret

    @internal
    @access("event")
    def _get_waitlist(self, rs: RequestState, event_id: int,
                      part_ids: Optional[Collection[int]] = None,
                      ) -> dict[int, Optional[list[int]]]:
        """Compute the waitlist in order for the given parts.

        Registrations with an empty waitlist field wil be placed at the end of the
        waitlist. The registration id is used as a tie breaker.

        :returns: Part id mapping to None, if no waitlist ordering is defined
            or a list of registration ids otherwise.
        """
        event_id = affirm(vtypes.ID, event_id)
        part_ids = affirm_set(vtypes.ID, part_ids or set())
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            if not part_ids:
                part_ids = set(event.parts.keys())
            elif not part_ids <= event.parts.keys():
                raise ValueError(n_("Unknown part for the given event."))
            ret: dict[int, Optional[list[int]]] = {}
            waitlist = const.RegistrationPartStati.waitlist
            query = ("SELECT id, fields FROM event.registrations"
                     " WHERE event_id = %s")
            for part_id in part_ids:
                part = event.parts[part_id]
                if not part.waitlist_field:
                    ret[part_id] = None
                    continue
                field_name = part.waitlist_field.field_name
                query = f"""
                    SELECT reg.id
                    FROM event.registrations AS reg
                        LEFT JOIN event.registration_parts AS rparts
                            ON reg.id = rparts.registration_id
                    WHERE rparts.part_id = %s AND rparts.status = %s
                    ORDER BY
                        COALESCE((reg.fields->>'{field_name}')::int, 2^31), reg.id
                """
                data = self.query_all(rs, query, (part_id, waitlist))
                ret[part_id] = [e['id'] for e in data]
            return ret

    @access("event")
    def get_waitlist(self, rs: RequestState, event_id: int,
                     part_ids: Optional[Collection[int]] = None,
                     ) -> dict[int, Optional[list[int]]]:
        """Public wrapper around _get_waitlist. Adds privilege check."""
        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Must be orga to access full waitlist."))
        return self._get_waitlist(rs, event_id, part_ids)

    @access("event")
    def get_waitlist_position(self, rs: RequestState, event_id: int,
                              part_ids: Optional[Collection[int]] = None,
                              persona_id: Optional[int] = None,
                              ) -> dict[int, Optional[int]]:
        """Compute the waitlist position of a user for the given parts.

        :returns: Mapping of part id to position on waitlist or None if user is
            not on the waitlist in that part.
        """
        full_waitlist = self._get_waitlist(rs, event_id, part_ids)
        if persona_id is None:
            persona_id = rs.user.persona_id
        if persona_id != rs.user.persona_id:
            if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
                raise PrivilegeError(
                    n_("Must be orga to access full waitlist."))
        reg_ids = self.list_registrations(rs, event_id, persona_id)
        if not reg_ids:
            raise ValueError(n_("Not registered for this event."))
        reg_id = unwrap(reg_ids.keys())
        ret: dict[int, Optional[int]] = {}
        for part_id, waitlist in full_waitlist.items():
            try:
                # If `reg_id` is not in the list, a ValueError will be raised.
                # Offset the index by one.
                ret[part_id] = (waitlist or []).index(reg_id) + 1
            except ValueError:
                ret[part_id] = None
        return ret

    @access("event")
    def registrations_by_course(
            self, rs: RequestState, event_id: int, course_id: Optional[int] = None,
            track_id: Optional[int] = None,
            position: Optional[InfiniteEnum[CourseFilterPositions]] = None,
            reg_ids: Optional[Collection[int]] = None,
            reg_states: Collection[const.RegistrationPartStati] =
            (const.RegistrationPartStati.participant,),
    ) -> dict[int, int]:
        """List registrations of an event pertaining to a certain course.

        This is a filter function, mainly for the course assignment tool.

        :param position: A :py:class:`cdedb.common.CourseFilterPositions`
        :param reg_ids: List of registration states (in any part) to filter for
        """
        event_id = affirm(vtypes.ID, event_id)
        track_id = affirm_optional(vtypes.ID, track_id)
        course_id = affirm_optional(vtypes.ID, course_id)
        position = affirm_optional(InfiniteEnum[CourseFilterPositions], position)
        reg_ids = reg_ids or set()
        reg_ids = affirm_set(vtypes.ID, reg_ids)
        reg_states = affirm_set(const.RegistrationPartStati, reg_states)
        if (not self.is_admin(rs)
                and not self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Not privileged."))
        query = """SELECT DISTINCT
            regs.id, regs.persona_id
        FROM
            event.registrations AS regs
            LEFT OUTER JOIN
                event.registration_parts
            AS rparts ON rparts.registration_id = regs.id
            LEFT OUTER JOIN
                event.course_tracks
            AS course_tracks ON course_tracks.part_id = rparts.part_id
            LEFT OUTER JOIN
                event.registration_tracks
            AS rtracks ON rtracks.registration_id = regs.id
                AND rtracks.track_id = course_tracks.id
            LEFT OUTER JOIN
                event.course_choices
            AS choices ON choices.registration_id = regs.id
                AND choices.track_id = course_tracks.id"""
        conditions = ["regs.event_id = %s", "rparts.status = ANY(%s)"]
        params: list[Any] = [event_id, reg_states]
        if track_id:
            conditions.append("course_tracks.id = %s")
            params.append(track_id)
        if position is not None:
            cfp = CourseFilterPositions
            sub_conditions = []
            if position.enum in (cfp.instructor, cfp.anywhere):
                if course_id:
                    sub_conditions.append("rtracks.course_instructor = %s")
                    params.append(course_id)
                else:
                    sub_conditions.append("rtracks.course_instructor IS NULL")
            if position.enum in (cfp.any_choice, cfp.anywhere):
                if course_id:
                    sub_conditions.append(
                        "(choices.course_id = %s AND "
                        " choices.rank < course_tracks.num_choices)")
                    params.append(course_id)
                else:
                    sub_conditions.append(
                        "(choices.course_id IS NULL AND "
                        " choices.rank < course_tracks.num_choices)")
            if position.enum == cfp.specific_rank:
                if course_id:
                    sub_conditions.append(
                        "(choices.course_id = %s AND choices.rank = %s)")
                    params.extend((course_id, position.int))
                else:
                    sub_conditions.append(
                        "(choices.course_id IS NULL AND choices.rank = %s)")
                    params.append(position.int)
            if position.enum in (cfp.assigned, cfp.anywhere):
                if course_id:
                    sub_conditions.append("rtracks.course_id = %s")
                    params.append(course_id)
                else:
                    sub_conditions.append("rtracks.course_id IS NULL")
            if sub_conditions:
                conditions.append(f"( {' OR '.join(sub_conditions)} )")
        if reg_ids:
            conditions.append("regs.id = ANY(%s)")
            params.append(reg_ids)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event")
    def get_num_registrations_by_part(self, rs: RequestState, event_id: int,
                                      stati: Collection[const.RegistrationPartStati],
                                      include_total: bool = False,
                                      ) -> dict[Optional[int], int]:
        """Count registrations per part.

        If selected, count total registration count (returned with part_id `None`).
        """
        event_id = affirm(vtypes.ID, event_id)
        stati = affirm_set(const.RegistrationPartStati, stati)
        # count per part
        q = """
            SELECT part_id, COUNT(*) AS num
            FROM event.registration_parts rp
            JOIN event.event_parts ep on ep.id = rp.part_id
            WHERE ep.event_id = %s AND rp.status = ANY(%s)
            GROUP BY part_id
        """
        res = {
            e['part_id']: e['num']
            for e in self.query_all(rs, q, (event_id, stati))
        }
        if include_total:
            # total registration count
            q = """
                SELECT COUNT(DISTINCT registration_id)
                FROM event.registration_parts rp
                JOIN event.event_parts ep on ep.id = rp.part_id
                WHERE ep.event_id = %s AND rp.status = ANY(%s)
            """
            res[None] = unwrap(self.query_one(rs, q, (event_id, stati)))
        return res

    @access("event")
    def get_registration_payment_info(self, rs: RequestState, event_id: int,
                                      ) -> tuple[Optional[bool], bool]:
        """Small helper to get information for the dashboard pages.

        The first returned flag is None iff there is no registration for the user.
        Otherwise, it tells whether the user is involved in any part.
        The second flag tells whether there is still some amount left to pay; this
        can only be True if the first flag is True.
        """
        registration_ids = self.list_registrations(rs, event_id,
                                                   rs.user.persona_id).keys()
        if registration_ids:
            registration = self.get_registration(rs, unwrap(registration_ids))
            if not any(part['status'].has_to_pay()
                       for part in registration['parts'].values()):
                return any(part['status'].is_involved()
                           for part in registration['parts'].values()), False
            # TODO: Use Registration.remaining_owed here.
            return True, registration['amount_owed'] > registration['amount_paid']
        else:
            return None, False

    @access("event", "ml_admin")
    def get_registrations(self, rs: RequestState, registration_ids: Collection[int],
                          ) -> CdEDBObjectMap:
        """Retrieve data for some registrations.

        All have to be from the same event.
        You must be orga to get additional access to all registrations which are
        not your own. If you are participant of the event, you get access to
        data from other users, being also participant in the same event (this is
        important for the online participant list).
        This includes the following additional data:

        * parts: per part data (like lodgement),
        * tracks: per track data (like course choices)

        ml_admins are allowed to do this to be able to manage
        subscribers of event mailinglists.
        """
        registration_ids = affirm_set(vtypes.ID, registration_ids)
        with Atomizer(rs):
            # Check associations.
            associated = self.sql_select(rs, "event.registrations",
                                         ("persona_id", "event_id"), registration_ids)
            if not associated:
                return {}
            events = {e['event_id'] for e in associated}
            personas = {e['persona_id'] for e in associated}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))
            event_id = unwrap(events)
            # Select appropriate stati filter.
            stati = set(m for m in const.RegistrationPartStati)
            # orgas and admins have full access to all data
            # ml_admins are allowed to do this to be able to manage
            # subscribers of event mailinglists.
            # finance_admins are allowed here to book event fees.
            is_privileged = (
                self.is_orga(rs, event_id=event_id) or self.is_admin(rs)
                or {"ml_admin", "finance_admin"}.intersection(rs.user.roles))
            if not is_privileged:
                if rs.user.persona_id not in personas:
                    raise PrivilegeError(n_("Not privileged."))
                elif not personas <= {rs.user.persona_id}:
                    # Permission check is done later when we know more
                    stati = {const.RegistrationPartStati.participant}

            ret = self._get_registration_data(rs, event_id, registration_ids)

            pdata = self.sql_select(
                rs, "event.registration_parts", REGISTRATION_PART_FIELDS,
                registration_ids, entity_key="registration_id")
            for p in pdata:
                p['status'] = const.RegistrationPartStati(p['status'])
                ret[p['registration_id']].setdefault('parts', {})[p['part_id']] = p
            # Limit to registrations matching stati filter in any part.
            for anid in tuple(ret):
                if not any(e['status'] in stati for e in ret[anid]['parts'].values()):
                    del ret[anid]

            # Here comes the promised permission check
            if not is_privileged and all(reg['persona_id'] != rs.user.persona_id
                                         for reg in ret.values()):
                raise PrivilegeError(n_("No participant of event."))

            tdata = self.sql_select(
                rs, "event.registration_tracks", REGISTRATION_TRACK_FIELDS,
                registration_ids, entity_key="registration_id")
            choices = self.sql_select(
                rs, "event.course_choices",
                ("registration_id", "track_id", "course_id", "rank"), registration_ids,
                entity_key="registration_id")
            event_fields = models.EventField.many_from_database(
                self._get_event_fields(rs, event_id).values())
            for reg in ret.values():
                reg['tracks'] = {}
                reg['fields'] = cast_fields(reg['fields'], event_fields)
            for reg_track in tdata:
                reg = ret[reg_track['registration_id']]
                reg['tracks'][reg_track['track_id']] = reg_track
                reg_track['choices'] = {}
            for choice in choices:
                reg_track = ret[choice['registration_id']]['tracks'][choice['track_id']]
                reg_track['choices'][choice['course_id']] = choice['rank']
            for reg in ret.values():
                for reg_track in reg['tracks'].values():
                    tmp = reg_track['choices']
                    reg_track['choices'] = xsorted(tmp.keys(), key=tmp.get)

        return ret

    class _GetRegistrationProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int) -> CdEDBObject: ...
    get_registration: _GetRegistrationProtocol = singularize(
        get_registrations, "registration_ids", "registration_id")

    @access("event")
    def set_registration(self, rs: RequestState, data: CdEDBObject,
                         change_note: Optional[str] = None, orga_input: bool = True,
                         ) -> DefaultReturnCode:
        """Public entry point for setting a registration. Perform sanity checks after.
        """
        data = affirm(vtypes.Registration, data)
        change_note = affirm_optional(str, change_note)

        with Atomizer(rs):
            # Retrieve some basic data about the registration.
            current = self._get_registration_info(rs, reg_id=data['id'])
            if current is None:
                raise ValueError(n_("Registration does not exist."))

            # Actually alter the registration.
            ret = self._set_registration(rs, data, change_note, orga_input)

            # Perform sanity checks.
            self._track_groups_sanity_check(rs, current['event_id'])

        return ret

    @access("event")
    def set_registrations(self, rs: RequestState, data: Collection[CdEDBObject],
                          change_note: Optional[str] = None) -> DefaultReturnCode:
        """Helper for setting multiple registrations at once.

        All registrations must belong to the same event.
        Perform sanity checks only once after everything has been updated.
        """
        data = affirm_array(vtypes.Registration, data)
        change_note = affirm_optional(str, change_note)

        if not data:
            return 1

        with Atomizer(rs):
            event_ids = {e['event_id'] for e in self.sql_select(
                rs, "event.registrations", ("event_id",),
                [datum['id'] for datum in data])}
            if not len(event_ids) == 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))
            event_id = unwrap(event_ids)
            if not (self.is_orga(rs, event_id=event_id) or self.is_admin(rs)):
                raise PrivilegeError

            ret = 1
            for datum in data:
                ret *= self._set_registration(rs, datum, change_note, orga_input=True)

            self._track_groups_sanity_check(rs, event_id)

        return ret

    @staticmethod
    def _get_status_change_log_message(
            rs: RequestState, old_state: CdEDBObject, update: CdEDBObject,
            event_part: models.EventPart,
    ) -> Optional[str]:
        """Uninlined code from _set_registration for better readability."""
        old_status = const.RegistrationPartStati(old_state['status'])
        g = rs.log_gettext

        if 'status' in update and update['status'] != old_status:
            change_note = f"{g(str(old_status))} -> {g(str(update['status']))}"
            if len(event_part.event.parts) > 1:
                change_note = f"{event_part.shortname}: {change_note}"
            return change_note
        return None

    def _set_registration(self, rs: RequestState, data: CdEDBObject,
                          change_note: Optional[str] = None, orga_input: bool = True,
                          ) -> DefaultReturnCode:
        """Update some keys of a registration.

        The syntax for updating the non-trivial keys fields, parts and
        choices is as follows:

        * If the key 'fields' is present it must be a dict and is used to
          updated the stored value (in a python dict.update sense).
        * If the key 'parts' is present, the associated dict mapping the
          part ids to the respective data sets can contain an arbitrary
          number of entities, absent entities are not modified. Entries are
          created/updated as applicable.
        * If the key 'tracks' is present, the associated dict mapping the
          track ids to the respective data sets can contain an arbitrary
          number of entities, absent entities are not
          modified. Entries are created/updated as applicable. The
          'choices' key is handled separately and if present replaces
          the current list of course choices.
        """
        with Atomizer(rs):
            # Retrieve some basic data about the registration.
            current = self._get_registration_info(rs, reg_id=data['id'])
            if current is None:
                raise ValueError(n_("Registration does not exist."))
            persona_id, event_id = current['persona_id'], current['event_id']
            self.assert_offline_lock(rs, event_id=event_id)
            if (persona_id != rs.user.persona_id
                    and not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)):
                raise PrivilegeError(n_("Not privileged."))
            event = self.get_event(rs, event_id)
            if "amount_owed" in data:
                del data["amount_owed"]

            # now we get to do the actual work
            rdata = {k: v for k, v in data.items()
                     if k in REGISTRATION_FIELDS and k != "fields"}
            ret = 1
            if len(rdata) > 1:
                ret *= self.sql_update(rs, "event.registrations", rdata)
            if 'fields' in data:
                # delayed validation since we need additional info
                fdata = affirm(
                    vtypes.EventAssociatedFields, data['fields'],
                    fields=event.fields,
                    association=const.FieldAssociations.registration)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.registrations",
                                                    fupdate)
            if 'parts' in data:
                parts = data['parts']
                if not event.parts.keys() >= parts.keys():
                    raise ValueError(n_("Non-existing parts specified."))
                existing_data = {e['part_id']: e for e in self.sql_select(
                    rs, "event.registration_parts",
                    ("id", "part_id", "status"),
                    (data['id'],), entity_key="registration_id")}
                existing = {e['part_id']: e['id'] for e in existing_data.values()}
                new = {x for x in parts if x not in existing}
                updated = {x for x in parts
                           if x in existing and parts[x] is not None}
                deleted = {x for x in parts
                           if x in existing and parts[x] is None}
                for x in new:
                    new_part = copy.deepcopy(parts[x])
                    new_part['registration_id'] = data['id']
                    new_part['part_id'] = x
                    ret *= self.sql_insert(rs, "event.registration_parts",
                                           new_part)
                for x in updated:
                    update = copy.deepcopy(parts[x])
                    update['id'] = existing[x]
                    if status_change_note := self._get_status_change_log_message(
                            rs, existing_data[x], update, event.parts[x]):
                        self.event_log(
                            rs, const.EventLogCodes.registration_status_changed,
                            event_id, persona_id, status_change_note)
                    ret *= self.sql_update(rs, "event.registration_parts", update)
                if deleted:
                    raise NotImplementedError(n_("This is not useful."))
            if 'tracks' in data:
                tracks = data['tracks']
                if not set(tracks).issubset(event.tracks):
                    raise ValueError(n_("Non-existing tracks specified."))
                aux = self.get_course_choice_validation_aux(
                    rs, event_id, registration_id=data['id'], orga_input=orga_input)
                existing = {e['track_id']: e['id'] for e in self.sql_select(
                    rs, "event.registration_tracks", ("id", "track_id"),
                    (data['id'],), entity_key="registration_id")}
                new = {x for x in tracks if x not in existing}
                updated = {x for x in tracks
                           if x in existing and tracks[x] is not None}
                deleted = {x for x in tracks
                           if x in existing and tracks[x] is None}
                for x in new:
                    new_track = copy.deepcopy(tracks[x])
                    choices = new_track.pop('choices', None)
                    self._set_course_choices(
                        rs, data['id'], x, choices, aux=aux)
                    new_track['registration_id'] = data['id']
                    new_track['track_id'] = x
                    ret *= self.sql_insert(rs, "event.registration_tracks",
                                           new_track)
                for x in updated:
                    update = copy.deepcopy(tracks[x])
                    choices = update.pop('choices', None)
                    self._set_course_choices(
                        rs, data['id'], x, choices, aux=aux)
                    update['id'] = existing[x]
                    ret *= self.sql_update(rs, "event.registration_tracks",
                                           update)
                if deleted:
                    raise NotImplementedError(n_("This is not useful."))

            # Recalculate the amount owed after all changes have been applied.
            current = self.get_registration(rs, data['id'])
            update = {
                'id': data['id'],
                'amount_owed': self._calculate_single_fee(rs, current, event=event),
            }
            ret *= self.sql_update(rs, "event.registrations", update)
            self.event_log(
                rs, const.EventLogCodes.registration_changed, event_id,
                persona_id=persona_id, change_note=change_note)

            # Sanity check is handled by public entry point.

        return ret

    @access("event")
    def create_registration(self, rs: RequestState, data: CdEDBObject,
                            orga_input: bool = True) -> DefaultReturnCode:
        """Make a new registration.

        The data must contain a dataset for each part and each track
        and may not contain a value for 'fields', which is initialized
        to a default value.
        """
        data = affirm(vtypes.Registration, data, creation=True)
        event = self.get_event(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata, fields=event.fields,
            association=const.FieldAssociations.registration)
        if (data['persona_id'] != rs.user.persona_id
                and not self.is_orga(rs, event_id=data['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        with Atomizer(rs):
            if not self.core.verify_id(rs, data['persona_id'], is_archived=False):
                raise ValueError(n_("This user does not exist or is archived."))
            if not self.core.verify_persona(rs, data['persona_id'], {"event"}):
                raise ValueError(n_("This user is not an event user."))
            if self.list_registrations(rs, data['event_id'], data['persona_id']):
                raise ValueError(n_("Already registered."))
            self.assert_offline_lock(rs, event_id=data['event_id'])
            persona = self.core.get_persona(rs, data['persona_id'])
            data['fields'] = fdata
            data['is_member'] = persona['is_member']
            data['amount_owed'] = self._calculate_single_fee(rs, data, event=event)
            data['fields'] = PsycoJson(fdata)
            part_ids = {e['id'] for e in self.sql_select(
                rs, "event.event_parts", ("id",), (data['event_id'],),
                entity_key="event_id")}
            if part_ids != set(data['parts'].keys()):
                raise ValueError(n_("Missing part dataset."))
            track_ids = {e['id'] for e in self.sql_select(
                rs, "event.course_tracks", ("id",), part_ids, entity_key="part_id")}
            if track_ids != set(data['tracks'].keys()):
                raise ValueError(n_("Missing track dataset."))
            rdata = {k: v for k, v in data.items() if k in REGISTRATION_FIELDS}
            new_id = self.sql_insert(rs, "event.registrations", rdata)

            # Uninlined code from set_registration to make this more
            # performant.
            #
            # insert parts
            for part_id, part in data['parts'].items():
                new_part = copy.deepcopy(part)
                new_part['registration_id'] = new_id
                new_part['part_id'] = part_id
                self.sql_insert(rs, "event.registration_parts", new_part)
            aux = self.get_course_choice_validation_aux(
                rs, event.id, registration_id=new_id, orga_input=orga_input)
            # insert tracks
            for track_id, track in data['tracks'].items():
                new_track = copy.deepcopy(track)
                choices = new_track.pop('choices', None)
                self._set_course_choices(
                    rs, new_id, track_id, choices, aux=aux, new_registration=True)
                new_track['registration_id'] = new_id
                new_track['track_id'] = track_id
                self.sql_insert(rs, "event.registration_tracks", new_track)
            self._track_groups_sanity_check(rs, data['event_id'])
            self.event_log(
                rs, const.EventLogCodes.registration_created, data['event_id'],
                persona_id=data['persona_id'])
        return new_id

    @access("event")
    def delete_registration_blockers(self, rs: RequestState,
                                     registration_id: int) -> DeletionBlockers:
        """Determine what keeps a registration from being deleted.

        Possible blockers:

        * registration_parts: The registration's registration parts.
        * registration_tracks: The registration's registration tracks.
        * course_choices: The registrations course choices.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        registration_id = affirm(vtypes.ID, registration_id)
        blockers = {}

        reg_parts = self.sql_select(
            rs, "event.registration_parts", ("id",), (registration_id,),
            entity_key="registration_id")
        if reg_parts:
            blockers["registration_parts"] = [e["id"] for e in reg_parts]

        reg_tracks = self.sql_select(
            rs, "event.registration_tracks", ("id",), (registration_id,),
            entity_key="registration_id")
        if reg_tracks:
            blockers["registration_tracks"] = [e["id"] for e in reg_tracks]

        course_choices = self.sql_select(
            rs, "event.course_choices", ("id",), (registration_id,),
            entity_key="registration_id")
        if course_choices:
            blockers["course_choices"] = [e["id"] for e in course_choices]

        return blockers

    @access("event")
    def delete_registration(self, rs: RequestState, registration_id: int,
                            cascade: Optional[Collection[str]] = None,
                            ) -> DefaultReturnCode:
        """Remove a registration.

        :param cascade: Specify which deletion blockers to cascadingly remove
            or ignore. If None or empty, cascade none.
        """
        registration_id = affirm(vtypes.ID, registration_id)
        reg = self.get_registration(rs, registration_id)
        if (not self.is_orga(rs, event_id=reg['event_id'])
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=reg['event_id'])

        blockers = self.delete_registration_blockers(rs, registration_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "registration",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            # cascade specified blockers
            if cascade:
                if "registration_parts" in cascade:
                    ret *= self.sql_delete(rs, "event.registration_parts",
                                           blockers["registration_parts"])
                if "registration_tracks" in cascade:
                    ret *= self.sql_delete(rs, "event.registration_tracks",
                                           blockers["registration_tracks"])
                if "course_choices" in cascade:
                    ret *= self.sql_delete(rs, "event.course_choices",
                                           blockers["course_choices"])

                # check if registration is deletable after cascading
                blockers = self.delete_registration_blockers(
                    rs, registration_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "event.registrations", registration_id)
                self.event_log(rs, const.EventLogCodes.registration_deleted,
                               reg['event_id'], persona_id=reg['persona_id'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "registration", "block": blockers.keys()})
        return ret

    def _update_registrations_amount_owed(self, rs: RequestState, event_id: int,
                                          ) -> DefaultReturnCode:
        self.affirm_atomized_context(rs)
        registration_ids = self.list_registrations(rs, event_id)
        fees = self.calculate_fees(rs, registration_ids)

        # TODO: make this more efficient by cahing parse results and evaluators somehow.

        ret = 1
        for reg_id, amount_owed in fees.items():
            update = {
                'id': reg_id,
                'amount_owed': amount_owed,
            }
            ret *= self.sql_update(rs, "event.registrations", update)

        return ret

    @access("finance_admin")
    def list_amounts_owed(self, rs: RequestState, persona_id: int,
                          ) -> dict[int, decimal.Decimal]:
        """List the remaining amount owed for every registration of the given user."""
        persona_id = affirm(vtypes.ID, persona_id)
        query = f"""
            SELECT event_id, amount_owed - amount_paid AS amount
            FROM {models.Registration.database_table}
            WHERE persona_id = %s
        """
        params = [persona_id]

        return {
            e['event_id']: e['amount'] for e in self.query_all(rs, query, params)
        }

    @access("finance_admin")
    def get_amount_owed(self, rs: RequestState, persona_id: int, event_id: int,
                        ) -> Optional[decimal.Decimal]:
        """Retrieve the remaining amount owed for a single persona for one event."""
        persona_id = affirm(vtypes.ID, persona_id)
        event_id = affirm(vtypes.ID, event_id)
        query = f"""
            SELECT amount_owed - amount_paid AS amount
            FROM {models.Registration.database_table}
            WHERE persona_id = %s AND event_id = %s
        """
        params = [persona_id, event_id]

        return unwrap(self.query_one(rs, query, params))

    @access("finance_admin")
    def get_registration_id(self, rs: RequestState, persona_id: int, event_id: int,
                            ) -> Optional[int]:
        """Retrieve the registration id of the given persona for the event if any."""
        persona_id = affirm(vtypes.ID, persona_id)
        event_id = affirm(vtypes.ID, event_id)
        registration_ids = self.list_registrations(rs, event_id, persona_id)
        if not registration_ids:
            return None
        return unwrap(registration_ids.keys())

    @access("event")
    def calculate_complex_fee(self, rs: RequestState, registration_id: int,
                              visual_debug: bool = False) -> RegistrationFeeData:
        """Public access point for retrieving complex fee data."""
        registration_id = affirm(vtypes.ID, registration_id)
        registration = self.get_registration(rs, registration_id)
        event = self.get_event(rs, registration['event_id'])
        return self._calculate_complex_fee(rs, registration, event=event,
                                           visual_debug=visual_debug)

    def _calculate_single_fee(self, rs: RequestState, reg: CdEDBObject, *,
                              event: models.Event) -> decimal.Decimal:
        """Helper to only calculate return the fee amount for a single registration."""
        return self._calculate_complex_fee(rs, reg, event=event).amount

    @staticmethod
    def _calculate_complex_fee(rs: RequestState, reg: CdEDBObject, *,
                               event: models.Event, visual_debug: bool = False,
                               ) -> RegistrationFeeData:
        """Helper function to calculate the fee for one registration.

        This is used inside `create_registration` and `set_registration`,
        so we take the full registration and event as input instead of
        retrieving them via id.

        For the set of parts the registration has to pay for, every subset is checked.
        If the subset does not violate any MEP constraints, the total of all it's parts'
        fees is calculated. The final fee will be the maximum of all such totals.

        :param visual_debug: If True, create a html representation of the
            evaluated condition.
        """
        ret = {}

        reg_part_involvement = {
            event.parts[part_id].shortname: rp['status'].has_to_pay()
            for part_id, rp in reg['parts'].items()
        }
        reg_bool_fields = {
            str(f.field_name): reg['fields'].get(f.field_name, False)
            for f in event.fields.values()
            if f.association == const.FieldAssociations.registration
               and f.kind == const.FieldDatatypes.bool
        }
        for tmp_is_member in (True, False):
            # Other bools can be added here, but also require adjustment to the parser.
            other_bools = {
                'is_orga': reg.get('is_orga', reg['persona_id'] in event.orgas),
                'is_member': tmp_is_member,
                'any_part': any(reg_part_involvement.values()),
                'all_parts': all(reg_part_involvement.values()),
            }
            amount = decimal.Decimal(0)
            active_fees = set()
            fees_by_kind: dict[const.EventFeeType, decimal.Decimal] = defaultdict(
                decimal.Decimal)
            visual_debug_data: dict[int, str] = {}
            for fee in event.fees.values():
                parse_result = fcp_parsing.parse(fee.condition)
                if fcp_evaluation.evaluate(
                        parse_result, reg_bool_fields, reg_part_involvement,
                        other_bools):
                    amount += fee.amount
                    active_fees.add(fee.id)
                    fees_by_kind[fee.kind] += fee.amount
                if visual_debug:
                    visual_debug_data[fee.id] = fcp_roundtrip.visual_debug(
                        parse_result, reg_bool_fields, reg_part_involvement,
                        other_bools,
                    )[1]
            ret[tmp_is_member] = RegistrationFee(
                amount, active_fees, visual_debug_data, fees_by_kind)

        return RegistrationFeeData(
            member_fee=ret[True], nonmember_fee=ret[False], is_member=reg['is_member'],
        )

    @access("event")
    def precompute_fee(self, rs: RequestState, event_id: int, persona_id: Optional[int],
                       part_ids: Collection[int], is_member: Optional[bool],
                       is_orga: Optional[bool], field_values: dict[str, bool],
                       ) -> RegistrationFeeData:
        """Alternate access point to calculate a single fee, that does not need
        an existing registration.

        :param part_ids: Collection of part ids the user is (supposedly) registered for.
        :param is_member: Optional override for membership status in fee calculation.
        :param field_values: Mapping of `f"field.{field_id}"` to value of the field.
        :param is_orga: Optional override for orga status in fee calculation.
        """
        event_id = affirm(vtypes.ID, event_id)
        persona_id = affirm_optional(vtypes.ID, persona_id)
        part_ids = affirm_set(vtypes.ID, part_ids)
        is_member = affirm_optional(bool, is_member)
        is_orga = affirm_optional(bool, is_orga)
        field_values = affirm(Mapping, field_values)  # type: ignore[type-abstract]

        event = self.get_event(rs, event_id)

        registration_id = None
        if persona_id:
            registration_id = unwrap(
                self.list_registrations(rs, event_id, persona_id).keys() or None)

        if self.is_orga(rs, event_id=event_id):
            pass
        elif persona_id and persona_id == rs.user.persona_id and (
                event.is_open or registration_id):
            pass
        else:
            raise PrivilegeError

        reg = None
        if registration_id:
            reg = self.get_registration(rs, registration_id)

        fields = {}
        for field_id, field in event.fields.items():
            fn = field.field_name
            fields[fn] = field_values.get(f"field.{field_id}")
            if fields[fn] is None:
                fields[fn] = bool(reg['fields'].get(fn, False)) if reg else False

        fake_registration = {
            'persona_id': persona_id,
            'parts': {
                part_id: {
                    'status':
                        const.RegistrationPartStati.applied
                        if part_id in part_ids
                        else const.RegistrationPartStati.not_applied,
                }
                for part_id in event.parts
            },
            'fields': fields,
            'is_member': is_member,
            'is_orga': is_orga,
        }
        return self._calculate_complex_fee(
            rs, fake_registration, event=event, visual_debug=True)

    @access("event")
    def calculate_fees(self, rs: RequestState, registration_ids: Collection[int],
                       ) -> dict[int, decimal.Decimal]:
        """Calculate the total fees for some registrations.

        This should be called once for multiple registrations, as it would be
        somewhat expensive if called per registration.

        All registrations need to belong to the same event.

        The caller must have priviliged acces to that event.
        """
        registration_ids = affirm_set(vtypes.ID, registration_ids)

        with Atomizer(rs):
            associated = self.sql_select(rs, "event.registrations",
                                         ("event_id",), registration_ids)
            if not associated:
                return {}
            events = {e['event_id'] for e in associated}
            if len(events) > 1:
                raise ValueError(n_(
                    "Only registrations from exactly one event allowed."))

            event_id = unwrap(events)
            regs = self.get_registrations(rs, registration_ids)
            persona_ids = {e['persona_id'] for e in regs.values()}
            # finance_admins are allowed here to book event fees.
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)
                    and "finance_admin" not in rs.user.roles
                    and persona_ids != {rs.user.persona_id}):
                raise PrivilegeError(n_("Not privileged."))

            event = self.get_event(rs, event_id)

            ret: dict[int, decimal.Decimal] = {}
            for reg_id, reg in regs.items():
                ret[reg_id] = self._calculate_single_fee(rs, reg, event=event)
        return ret

    class _CalculateFeeProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int,
                     ) -> decimal.Decimal: ...
    calculate_fee: _CalculateFeeProtocol = singularize(
        calculate_fees, "registration_ids", "registration_id")

    @access("event")
    def get_fee_stats(self, rs: RequestState, event_id: int,
                      ) -> FeeStats:
        """Group and sum the paid fees by type.

        This calculates the sum over both owed and paid fees, for each kind of event
        fees individually. If people have paid more or less than the owed amount,
        special treatment is needed:

        * The share of the paid amount excessive the owed amount can not be assigned to
          a specific fee type, and is therefore not included.
        * If the paid amount is less than the owed amount, it can not be split into the
          respective kinds of owed fees at all. Therefore, these payments are not
          included at all.
        """
        event = self.get_event(rs, event_id)
        reg_ids = self.list_registrations(rs, event_id)

        ret: FeeStats = {
            'owed': dict.fromkeys(const.EventFeeType, decimal.Decimal(0)),
            'paid': dict.fromkeys(const.EventFeeType, decimal.Decimal(0)),
        }

        for reg in self.get_registrations(rs, reg_ids).values():
            reg_fee = self._calculate_complex_fee(rs, reg, event=event).fee
            paid = reg['amount_paid'] >= reg['amount_owed']
            for kind, amount in reg_fee.by_kind.items():
                ret['owed'][kind] += amount
                if paid:
                    ret['paid'][kind] += amount

        return ret

    @internal
    @access("finance_admin")
    def book_registration_payment(
            self, rs: RequestState, registration_id: int,
            amount: decimal.Decimal, date: datetime.date,
    ) -> CdEDBObject:
        """
        Add the given amount to the amount that was paid for this registration.

        The amount may be negative but not zero.

        The caller is responsible for validating the input, due to this being internal.

        Returns the new state of the registration for convenienve.
        """

        event_log_transfer_template = "{amount} am {date} gezahlt."
        event_log_reimbursement_template = "{amount} am {date} zurückerstattet."

        registration = self.get_registration(rs, registration_id)
        event_id = registration['event_id']

        if amount > 0:
            update = {
                'id': registration['id'],
                'payment': date,
                'amount_paid': registration['amount_paid'] + amount,
            }
            change_note = event_log_transfer_template.format(
                amount=money_filter(amount),
                date=date.strftime(PARSE_OUTPUT_DATEFORMAT),
            )
            self.sql_update(
                rs, models.Registration.database_table, update,
            )
            self.event_log(
                rs, const.EventLogCodes.registration_payment_received,
                event_id=event_id, change_note=change_note,
                persona_id=registration['persona_id'],
            )
            registration.update(update)
        elif amount < 0:
            update = {
                'id': registration['id'],
                'amount_paid': registration['amount_paid'] + amount,
                # Do not update payment date for reimbursements.
            }
            change_note = event_log_reimbursement_template.format(
                amount=money_filter(-amount),
                date=date.strftime(PARSE_OUTPUT_DATEFORMAT),
            )
            self.sql_update(
                rs, models.Registration.database_table, update,
            )
            self.event_log(
                rs, const.EventLogCodes.registration_payment_reimbursed,
                event_id=event_id, change_note=change_note,
                persona_id=registration['persona_id'],
            )
            registration.update(update)
        else:
            raise ValueError(n_("Cannot book fee with amount of zero."))

        return registration

    @access("finance_admin")
    def book_fees(self, rs: RequestState, event_id: int, data: Collection[CdEDBObject],
                  ) -> tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        data = affirm_array(vtypes.FeeBookingEntry, data)

        self.assert_offline_lock(rs, event_id=event_id)

        index = 0
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                for index, datum in enumerate(data):
                    self.book_registration_payment(
                        rs, datum['registration_id'], datum['amount'], datum['date'])
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None
        except Exception:  # pragma: no cover
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during fee transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index
        return True, len(data)
