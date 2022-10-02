#!/usr/bin/env python3

"""
The `EventRegistrationBackend` subclasses the `EventBaseBackend` and provides
functionality for managing registrations belonging to an event, including managing the
waitlist, calculating and booking event fees and checking the status of multiple
registrations at once for the mailinglist realm.
"""
import copy
import decimal
import itertools
from typing import (
    Any, Collection, Dict, Iterable, List, Mapping, NamedTuple, Optional, Protocol,
    Sequence, Set, Tuple, TypeVar,
)

import psycopg2.extensions

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import (
    access, affirm_array_validation as affirm_array,
    affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, cast_fields, internal, singularize,
)
from cdedb.backend.event.base import EventBaseBackend
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, CourseFilterPositions, DefaultReturnCode,
    DeletionBlockers, InfiniteEnum, PsycoJson, RequestState, glue, unwrap,
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

CourseChoiceValidationAux = NamedTuple(
    "CourseChoiceValidationAux", [
        ("course_segments", Mapping[int, Set[int]]),
        ("synced_tracks", Mapping[int, Set[int]]),
        ("involved_tracks", Set[int]),
    ])


class EventRegistrationBackend(EventBaseBackend):
    def _get_event_course_segments(self, rs: RequestState,
                                   event_id: int) -> Dict[int, Set[int]]:
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

    def _get_involved_tracks(self, rs: RequestState, registration_id: int
                             ) -> Set[int]:
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

    def _get_synced_tracks(self, rs: RequestState, event_id: int
                           ) -> Dict[int, Set[int]]:
        """Return a mapping of track id to ids of tracks synced to that track.

        The value will be an empty set for unsynced tracks.
        """
        q = """
            SELECT ct.id, COALESCE(synced_tracks, ARRAY[]::integer[]) AS synced_tracks
            FROM event.course_tracks AS ct
            JOIN event.event_parts ep on ep.id = ct.part_id
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
                                         part_ids: Optional[Collection[int]] = None,
                                         ) -> CourseChoiceValidationAux:
        """Gather auxilliary data necessary to validate course choices.

        Involved tracks can be determined from a registration id, by reading from the
        database or by specifying the involved parts explicitly, if necessary.
        """
        event_id = affirm(vtypes.ID, event_id)
        registration_id = affirm_optional(vtypes.ID, registration_id)
        part_ids = affirm_set(vtypes.ID, part_ids or ())
        if registration_id:
            involved_tracks = self._get_involved_tracks(rs, registration_id)
        elif part_ids:
            q = """
                SELECT ct.id
                FROM event.course_tracks ct
                JOIN event.event_parts ep on ep.id = ct.part_id
                WHERE ep.id = ANY(%s)
            """
            involved_tracks = {e['id'] for e in self.query_all(rs, q, (part_ids,))}
        else:
            involved_tracks = set()
        return CourseChoiceValidationAux(
            self._get_event_course_segments(rs, event_id),
            self._get_synced_tracks(rs, event_id),
            involved_tracks=involved_tracks,
        )

    @access("event")
    def validate_single_course_choice(self, rs: RequestState, course_id: int,  # pylint: disable=no-self-use
                                      track_id: int, aux: CourseChoiceValidationAux
                                      ) -> bool:
        """Check whether a course choice is allowed in a given track.

        Returns True for valid choice and False for invalid choice.

        :param aux: As returned by `get_course_choice_validation_aux`. This is
            dependent on the event and a specific registration.
        """
        # Either the course is offered in this track.
        if track_id in (offered_tracks := aux.course_segments[course_id]):
            return True
        # Or the course is offered in a synced track, that we are involved with.
        if aux.synced_tracks[track_id] & aux.involved_tracks & offered_tracks:
            return True
        # Otherwise the choice is not allowed.
        return False

    @access("event")
    def get_course_segments_per_track(self, rs: RequestState, event_id: int,
                                      active_only: bool = False) -> Dict[int, Set[int]]:
        query = """
            SELECT ct.id, ARRAY_REMOVE(ARRAY_AGG(segments.course_id), NULL) AS courses
            FROM (
                event.course_tracks AS ct
                LEFT JOIN event.event_parts AS ep ON ct.part_id = ep.id
                LEFT JOIN (
                    SELECT course_id, track_id, is_active
                    FROM event.course_segments AS segments
                    {}
                ) AS segments ON ct.id = segments.track_id
            )
            WHERE ep.event_id = %s
            GROUP BY ct.id
        """

        event_id = affirm(vtypes.ID, event_id)
        active_only = affirm(bool, active_only)
        query = query.format("WHERE is_active = True" if active_only else "")

        ret = {
            e['id']: set(e['courses'])
            for e in self.query_all(rs, query, (event_id,))
        }

        event = self.get_event(rs, event_id)
        for track_group in event['track_groups'].values():
            if not track_group['constraint_type'].is_sync():
                continue
            all_courses = set(itertools.chain.from_iterable(
                ret[track_id] for track_id in track_group['track_ids']))
            for track_id in track_group['track_ids']:
                ret[track_id] = set(all_courses)

        return ret

    def _set_course_choices(self, rs: RequestState, registration_id: int,
                            track_id: int, choices: Optional[Sequence[int]],
                            aux: CourseChoiceValidationAux,
                            new_registration: bool = False
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
        self, rs: RequestState, persona_id: int
    ) -> Dict[int, Dict[int, Dict[int, const.RegistrationPartStati]]]:
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
        ret: Dict[int, Dict[int, Dict[int, const.RegistrationPartStati]]] = {}
        for e in data:
            ret.setdefault(
                e['event_id'], {}
            ).setdefault(
                e['registration_id'], {}
            )[e['part_id']] = const.RegistrationPartStati(e['status'])
        return ret

    @access("event", "ml_admin")
    def list_registrations_personas(self, rs: RequestState, event_id: int,
                                    persona_ids: Collection[int] = None
                                    ) -> Dict[int, int]:
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
        if (persona_ids != {rs.user.persona_id}
                and not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)
                and "ml_admin" not in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))

        query = "SELECT id, persona_id FROM event.registrations"
        conditions = ["event_id = %s"]
        params: List[Any] = [event_id]
        if persona_ids:
            conditions.append("persona_id = ANY(%s)")
            params.append(persona_ids)
        query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("event", "ml_admin")
    def list_registrations(self, rs: RequestState, event_id: int, persona_id: int = None
                           ) -> Dict[int, int]:
        """Manual singularization of list_registrations_personas

        Handles default values properly.
        """
        if persona_id:
            return self.list_registrations_personas(rs, event_id, {persona_id})
        else:
            return self.list_registrations_personas(rs, event_id)

    @access("event")
    def list_participants(self, rs: RequestState, event_id: int) -> Dict[int, int]:
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
            stati: Collection[const.RegistrationPartStati]) -> Dict[int, bool]:
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
    def get_registration_map(self, rs: RequestState, event_ids: Collection[int]
                             ) -> Dict[Tuple[int, int], int]:
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
                      part_ids: Collection[int] = None
                      ) -> Dict[int, Optional[List[int]]]:
        """Compute the waitlist in order for the given parts.

        :returns: Part id maping to None, if no waitlist ordering is defined
            or a list of registration ids otherwise.
        """
        event_id = affirm(vtypes.ID, event_id)
        part_ids = affirm_set(vtypes.ID, part_ids or set())
        with Atomizer(rs):
            event = self.get_event(rs, event_id)
            if not part_ids:
                part_ids = event['parts'].keys()
            elif not part_ids <= event['parts'].keys():
                raise ValueError(n_("Unknown part for the given event."))
            ret: Dict[int, Optional[List[int]]] = {}
            waitlist = const.RegistrationPartStati.waitlist
            query = ("SELECT id, fields FROM event.registrations"
                     " WHERE event_id = %s")
            fields_by_id = {
                reg['id']: cast_fields(reg['fields'], event['fields'])
                for reg in self.query_all(rs, query, (event_id,))}
            for part_id in part_ids:
                part = event['parts'][part_id]
                if not part['waitlist_field']:
                    ret[part_id] = None
                    continue
                field_name = event['fields'][part['waitlist_field']]['field_name']
                query = ("SELECT reg.id, rparts.status"
                         " FROM event.registrations AS reg"
                         " LEFT OUTER JOIN event.registration_parts AS rparts"
                         " ON reg.id = rparts.registration_id"
                         " WHERE rparts.part_id = %s AND rparts.status = %s")
                data = self.query_all(rs, query, (part_id, waitlist))
                ret[part_id] = xsorted(
                    (reg['id'] for reg in data),
                    key=lambda r_id: (fields_by_id[r_id].get(field_name, 0) or 0, r_id))  # pylint: disable=cell-var-from-loop
            return ret

    @access("event")
    def get_waitlist(self, rs: RequestState, event_id: int,
                     part_ids: Collection[int] = None
                     ) -> Dict[int, Optional[List[int]]]:
        """Public wrapper around _get_waitlist. Adds privilege check."""
        if not (self.is_admin(rs) or self.is_orga(rs, event_id=event_id)):
            raise PrivilegeError(n_("Must be orga to access full waitlist."))
        return self._get_waitlist(rs, event_id, part_ids)

    @access("event")
    def get_waitlist_position(self, rs: RequestState, event_id: int,
                              part_ids: Collection[int] = None,
                              persona_id: int = None
                              ) -> Dict[int, Optional[int]]:
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
        ret: Dict[int, Optional[int]] = {}
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
            self, rs: RequestState, event_id: int, course_id: int = None,
            track_id: int = None, position: InfiniteEnum[CourseFilterPositions] = None,
            reg_ids: Collection[int] = None,
            reg_states: Collection[const.RegistrationPartStati] =
            (const.RegistrationPartStati.participant,)) -> Dict[int, int]:
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
        params: List[Any] = [event_id, reg_states]
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
            if position.enum in (cfp.any_choice, cfp.anywhere) and course_id:
                sub_conditions.append(
                    "(choices.course_id = %s AND "
                    " choices.rank < course_tracks.num_choices)")
                params.append(course_id)
            if position.enum == cfp.specific_rank and course_id:
                sub_conditions.append(
                    "(choices.course_id = %s AND choices.rank = %s)")
                params.extend((course_id, position.int))
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
                                      ) -> Dict[int, int]:
        event_id = affirm(vtypes.ID, event_id)
        stati = affirm_set(const.RegistrationPartStati, stati)
        q = """
            SELECT part_id, COUNT(*) AS num
            FROM event.registration_parts rp
            JOIN event.event_parts ep on ep.id = rp.part_id
            WHERE ep.event_id = %s AND rp.status = ANY(%s)
            GROUP BY part_id
        """
        return {
            e['part_id']: e['num']
            for e in self.query_all(rs, q, (event_id, stati))
        }

    @access("event")
    def get_registration_payment_info(self, rs: RequestState, event_id: int
                                      ) -> Tuple[Optional[bool], bool]:
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
            payment_pending = bool(
                not registration['payment']
                and self.calculate_fee(rs, unwrap(registration_ids)))
            return True, payment_pending
        else:
            return None, False

    @access("event", "ml_admin")
    def get_registrations(self, rs: RequestState, registration_ids: Collection[int]
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
            is_privileged = (self.is_orga(rs, event_id=event_id)
                             or self.is_admin(rs)
                             or "ml_admin" in rs.user.roles)
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
            event_fields = self._get_event_fields(rs, event_id)
            for anid in ret:
                if 'tracks' in ret[anid]:
                    raise RuntimeError()
                tracks = {e['track_id']: e for e in tdata
                          if e['registration_id'] == anid}
                for track_id in tracks:
                    tmp = {e['course_id']: e['rank'] for e in choices
                           if (e['registration_id'] == anid
                               and e['track_id'] == track_id)}
                    tracks[track_id]['choices'] = xsorted(tmp.keys(), key=tmp.get)
                ret[anid]['tracks'] = tracks
                ret[anid]['fields'] = cast_fields(ret[anid]['fields'], event_fields)

        return ret

    class _GetRegistrationProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int) -> CdEDBObject: ...
    get_registration: _GetRegistrationProtocol = singularize(
        get_registrations, "registration_ids", "registration_id")

    @access("event")
    def set_registration(self, rs: RequestState, data: CdEDBObject,
                         change_note: str = None) -> DefaultReturnCode:
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
        data = affirm(vtypes.Registration, data)
        change_note = affirm_optional(str, change_note)
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
                    fields=event['fields'],
                    association=const.FieldAssociations.registration)

                fupdate = {
                    'id': data['id'],
                    'fields': fdata,
                }
                ret *= self.sql_json_inplace_update(rs, "event.registrations",
                                                    fupdate)
            if 'parts' in data:
                parts = data['parts']
                if not event['parts'].keys() >= parts.keys():
                    raise ValueError(n_("Non-existing parts specified."))
                existing = {e['part_id']: e['id'] for e in self.sql_select(
                    rs, "event.registration_parts", ("id", "part_id"),
                    (data['id'],), entity_key="registration_id")}
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
                    ret *= self.sql_update(rs, "event.registration_parts",
                                           update)
                if deleted:
                    raise NotImplementedError(n_("This is not useful."))
            if 'tracks' in data:
                tracks = data['tracks']
                if not set(tracks).issubset(event['tracks']):
                    raise ValueError(n_("Non-existing tracks specified."))
                aux = self.get_course_choice_validation_aux(rs, event_id, data['id'])
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
                'amount_owed': self._calculate_single_fee(
                    rs, current, event=event)
            }
            ret *= self.sql_update(rs, "event.registrations", update)
            self.event_log(
                rs, const.EventLogCodes.registration_changed, event_id,
                persona_id=persona_id, change_note=change_note)
        return ret

    @access("event")
    def create_registration(self, rs: RequestState,
                            data: CdEDBObject) -> DefaultReturnCode:
        """Make a new registration.

        The data must contain a dataset for each part and each track
        and may not contain a value for 'fields', which is initialized
        to a default value.
        """
        data = affirm(vtypes.Registration, data, creation=True)
        event = self.get_event(rs, data['event_id'])
        fdata = data.get('fields') or {}
        fdata = affirm(
            vtypes.EventAssociatedFields, fdata, fields=event['fields'],
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
            data['fields'] = fdata
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
            aux = self.get_course_choice_validation_aux(rs, event['id'], new_id)
            # insert tracks
            for track_id, track in data['tracks'].items():
                new_track = copy.deepcopy(track)
                choices = new_track.pop('choices', None)
                self._set_course_choices(
                    rs, new_id, track_id, choices, aux=aux, new_registration=True)
                new_track['registration_id'] = new_id
                new_track['track_id'] = track_id
                self.sql_insert(rs, "event.registration_tracks", new_track)
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
                            cascade: Collection[str] = None
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

    @staticmethod
    def powerset(set_: Collection[T]) -> Iterable[Set[T]]:
        return itertools.chain.from_iterable(
            map(set, itertools.combinations(set_, n)) for n in range(len(set_) + 1))

    def _calculate_single_fee(self, rs: RequestState, reg: CdEDBObject, *,
                              event: CdEDBObject, is_member: bool = None
                              ) -> decimal.Decimal:
        """Helper function to calculate the fee for one registration.

        This is used inside `create_registration` and `set_registration`,
        so we take the full registration and event as input instead of
        retrieving them via id.

        For the set of parts the registration has to pay for, every subset is checked.
        If the subset does not violate any MEP constraints, the total of all it's parts'
        fees is calculated. The final fee will be the maximum of all such totals.

        :param is_member: If this is None, retrieve membership status here.
        """
        mep = const.EventPartGroupType.mutually_exclusive_participants
        zero = decimal.Decimal(0)

        # Reverse sorting by length slightly reduces runtime because of lazy evalution
        #  of `all()` and the fact, that larger part groups are more likely to have
        #  non-trivial intersections.
        parts_per_mep = xsorted(
            (pg['part_ids'] for pg in event['part_groups'].values()
             if pg['constraint_type'] == mep), key=len, reverse=True)

        # Precompute fees including fee modifiers for every registered-for part.
        fees_to_pay: Dict[int, decimal.Decimal] = {
            part_id: event['parts'][part_id]['fee']
            for part_id, rpart in reg['parts'].items()
            if rpart['status'].has_to_pay()
        }
        for fee_mod in event['fee_modifiers'].values():
            if reg['fields'].get(event['fields'][fee_mod['field_id']]['field_name']):
                if fee_mod['part_id'] in fees_to_pay:
                    fees_to_pay[fee_mod['part_id']] += fee_mod['amount']

        def total_cost(part_ids: Collection[int]) -> decimal.Decimal:
            """Calculate the total cost of the given parts for this registration."""
            return sum((fees_to_pay[part_id] for part_id in part_ids), start=zero)

        # Split all parts into those belonging to at least one part group and others.
        mep_parts = set(itertools.chain.from_iterable(
            pg['part_ids'] for pg in event['part_groups'].values()))
        other_parts = set(event['parts']) - mep_parts

        # Compute constant fee from non-part-group parts.
        fee = total_cost(other_parts & fees_to_pay.keys())

        # The following calculation is somewhat complicated and scales very poorly with
        #  the number of parts belonging to part groups.
        #  This is deemed acceptable because the number of part groups is not expected
        #  to exceed problematic threshholds.

        # For every legal subset of the registered-for parts calculate the total cost.
        #  Determine the maximum of those and add it to the fee.
        #  Legal subsets are those that only trivially intersect with all part groups.
        fee += max(
            (total_cost(ids_) for ids_ in self.powerset(mep_parts & fees_to_pay.keys())
             if all(len(mep_parts & ids_) <= 1 for mep_parts in parts_per_mep)),
            default=zero)

        # Add nonmember surcharge if applicable.
        if is_member is None:
            is_member = self.core.get_persona(
                rs, reg['persona_id'])['is_member']
        if not is_member:
            fee += event['nonmember_surcharge']

        return fee

    @access("event")
    def calculate_fees(self, rs: RequestState, registration_ids: Collection[int]
                       ) -> Dict[int, decimal.Decimal]:
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
            user_id = rs.user.persona_id
            if (not self.is_orga(rs, event_id=event_id)
                    and not self.is_admin(rs)
                    and {r['persona_id'] for r in regs.values()} != {user_id}):
                raise PrivilegeError(n_("Not privileged."))

            persona_ids = {e['persona_id'] for e in regs.values()}
            personas = self.core.get_personas(rs, persona_ids)

            event = self.get_event(rs, event_id)
            ret: Dict[int, decimal.Decimal] = {}
            for reg_id, reg in regs.items():
                is_member = personas[reg['persona_id']]['is_member']
                ret[reg_id] = self._calculate_single_fee(
                    rs, reg, event=event, is_member=is_member)
        return ret

    class _CalculateFeeProtocol(Protocol):
        def __call__(self, rs: RequestState, registration_id: int
                     ) -> decimal.Decimal: ...
    calculate_fee: _CalculateFeeProtocol = singularize(
        calculate_fees, "registration_ids", "registration_id")

    @access("event")
    def book_fees(self, rs: RequestState, event_id: int, data: Collection[CdEDBObject],
                  ) -> Tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        data = affirm_array(vtypes.FeeBookingEntry, data)

        if (not self.is_orga(rs, event_id=event_id)
                and not self.is_admin(rs)):
            raise PrivilegeError(n_("Not privileged."))
        self.assert_offline_lock(rs, event_id=event_id)

        index = 0
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                all_reg_ids = {datum['registration_id'] for datum in data}
                all_regs = self.get_registrations(rs, all_reg_ids)
                if any(reg['event_id'] != event_id for reg in all_regs.values()):
                    raise ValueError(n_("Mismatched registrations,"
                                        " not associated with the event."))
                for index, datum in enumerate(data):
                    reg_id = datum['registration_id']
                    update = {
                        'id': reg_id,
                        'payment': datum['date'],
                        'amount_paid': all_regs[reg_id]['amount_paid']
                                       + datum['amount'],
                    }
                    change_note = "{} am {} gezahlt.".format(
                        money_filter(datum['amount']),
                        date_filter(datum['original_date'], lang="de"))
                    count += self.set_registration(rs, update, change_note)
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
        return True, count
