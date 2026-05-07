#!/usr/bin/env python3

"""The past event backend provides means to catalogue information about
concluded events.
"""

import collections
import copy
import datetime
from collections.abc import Collection
from typing import Any, Optional, Protocol, TypeVar

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models_core
import cdedb.models.event as models_event
import cdedb.models.past_event as models
from cdedb.backend.common import (
    AbstractBackend,
    Silencer,
    access,
    affirm_validation as affirm,
    internal,
    singularize,
)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    DeletionBlockers,
    Error,
    RequestState,
    make_proxy,
    now,
    unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryScope
from cdedb.common.query.log_filter import PastEventLogFilter
from cdedb.common.sorting import xsorted
from cdedb.database.connection import Atomizer
from cdedb.database.query import ParamDict
from cdedb.models.common import CdEDataclassMap

T = TypeVar("T")


class PastEventBackend(AbstractBackend):
    """Handle concluded events.

    This is somewhere between CdE and event realm, so we split it into
    its own realm.
    """

    realm = "past_event"

    def __init__(self) -> None:
        super().__init__()
        self.event = make_proxy(EventBackend(), internal=True)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return "cde_admin" in rs.user.roles

    def past_event_log(
        self,
        rs: RequestState,
        *,
        code: const.PastEventLogCodes,
        pevent_id: Optional[int],
        pcourse_id: Optional[int] = None,
        persona_id: Optional[int] = None,
        change_note: Optional[str] = None,
    ) -> int:
        """Make an entry in the log for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "pevent_id": pevent_id,
            "pcourse_id": pcourse_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "past_event.log", data)

    @access("cde_admin", "event_admin", "auditor")
    def retrieve_past_log(
        self, rs: RequestState, log_filter: PastEventLogFilter
    ) -> CdEDBLog:
        """Get recorded activity for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm(PastEventLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @access("persona")
    def list_past_events(self, rs: RequestState) -> dict[int, str]:
        """List all concluded events.

        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM past_event.events"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde")
    def past_event_stats(self, rs: RequestState) -> CdEDBObjectMap:
        """Returns the number of courses and participants for each past event."""
        query = """
            SELECT
                events.id AS pevent_id,
                COALESCE(course_count, 0) AS courses,
                COALESCE(participant_count, 0) AS participants
            FROM (
                past_event.events
                LEFT OUTER JOIN (
                    SELECT
                        pevent_id, COUNT(*) AS course_count
                    FROM
                        past_event.courses
                    GROUP BY pevent_id
                ) AS course_counts ON course_counts.pevent_id = events.id
                LEFT OUTER JOIN (
                    SELECT
                        pevent_id, COUNT(*) AS participant_count
                        -- We have to do a subquery, as PSQL does not support
                        -- counting of more than one distinct column.
                    FROM (
                        SELECT DISTINCT
                            pevent_id, persona_id
                        FROM
                            past_event.participants
                    ) AS distinct_participants
                    GROUP BY
                        pevent_id
                ) AS participant_counts ON participant_counts.pevent_id = events.id
            )
        """
        return {e['pevent_id']: e for e in self.query_all(rs, query, [])}

    @access("cde", "event")
    def get_past_events(
        self, rs: RequestState, pevent_ids: Collection[int]
    ) -> CdEDataclassMap[models.PastEvent]:
        """Retrieve data for some concluded events."""
        pevent_ids = affirm(set[vtypes.ID], pevent_ids)
        return models.PastEvent.many_from_database(
            self.query_all(rs, *models.PastEvent.get_select_query(pevent_ids))
        )

    class _GetPastEventProtocol(Protocol):
        def __call__(self, rs: RequestState, pevent_id: int) -> models.PastEvent: ...

    get_past_event: _GetPastEventProtocol = singularize(
        get_past_events, "pevent_ids", "pevent_id"
    )

    @access("cde_admin", "event_admin")
    def set_past_event(
        self, rs: RequestState, pevent_id: int, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Update some keys of a concluded event."""
        pevent_id = affirm(vtypes.ID, pevent_id)
        data = affirm(models.PastEvent, data)
        data["id"] = pevent_id
        with Atomizer(rs):
            ret = self.sql_update(rs, models.PastEvent.database_table, data)
            self.past_event_log(
                rs, code=const.PastEventLogCodes.event_changed, pevent_id=pevent_id
            )
        return ret

    @access("cde_admin", "event_admin")
    def create_past_event(
        self, rs: RequestState, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Make a new concluded event."""
        data = affirm(models.PastEvent, data, creation=True)
        with Atomizer(rs):
            ret = self.sql_insert(rs, models.PastEvent.database_table, data)
            self.past_event_log(
                rs, code=const.PastEventLogCodes.event_created, pevent_id=ret
            )
        return ret

    @access("cde_admin")
    def delete_past_event_blockers(
        self, rs: RequestState, pevent_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a past event from being deleted.

        Possible blockers:

        * participants: A participant of the past event or one of its
                        courses.
        * courses: A course associated with the past event.
        * log: A log entry for the past event.
        * genesis cases: A genesis case associated with the past event.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        pevent_id = affirm(vtypes.ID, pevent_id)
        blockers = {}

        participants = self.sql_select(
            rs, "past_event.participants", ("id",), (pevent_id,), entity_key="pevent_id"
        )
        if participants:
            blockers["participants"] = [e["id"] for e in participants]

        courses = self.sql_select(
            rs, "past_event.courses", ("id",), (pevent_id,), entity_key="pevent_id"
        )
        if courses:
            blockers["courses"] = [e["id"] for e in courses]

        log = self.sql_select(
            rs, "past_event.log", ("id",), (pevent_id,), entity_key="pevent_id"
        )
        if log:
            blockers["log"] = [e["id"] for e in log]
        genesis_cases = self.sql_select(
            rs, "core.genesis_cases", ("id",), (pevent_id,), entity_key="pevent_id"
        )
        if genesis_cases:
            blockers["genesis_cases"] = [e["id"] for e in genesis_cases]

        return blockers

    @access("cde_admin")
    def delete_past_event(
        self,
        rs: RequestState,
        pevent_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Remove past event.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """

        pevent_id = affirm(vtypes.ID, pevent_id)
        blockers = self.delete_past_event_blockers(rs, pevent_id)
        if not cascade:
            cascade = set()
        cascade = affirm(set[str], cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "past_event",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            pevent = self.get_past_event(rs, pevent_id)
            if cascade:
                if "participants" in cascade:
                    assignments = self.sql_select(
                        rs,
                        "past_event.course_participants",
                        ["id"],
                        blockers["participants"],
                        entity_key="participant_id",
                    )
                    ret *= self.sql_delete(
                        rs,
                        "past_event.course_participants",
                        [e["id"] for e in assignments],
                    )
                    ret *= self.sql_delete(
                        rs, "past_event.participants", blockers["participants"]
                    )
                if "courses" in cascade:
                    with Silencer(rs):
                        for pcourse_id in blockers["courses"]:
                            casc = {"participants"} | (
                                {"genesis_cases", "log"} & cascade
                            )
                            ret *= self.delete_past_course(rs, pcourse_id, cascade=casc)
                if "log" in cascade:
                    ret *= self.sql_delete(rs, "past_event.log", blockers["log"])
                if "genesis_cases" in cascade:
                    for case_id in blockers["genesis_cases"]:
                        # we use sql_update instead of core.modify_genesis_case here,
                        #  since the latter is forbidden for finalized cases
                        update = {'id': case_id, 'pevent_id': None}
                        ret *= self.sql_update(rs, "core.genesis_cases", update)

                blockers = self.delete_past_event_blockers(rs, pevent_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "past_event.events", pevent_id)
                self.past_event_log(
                    rs,
                    code=const.PastEventLogCodes.event_deleted,
                    pevent_id=None,
                    persona_id=None,
                    change_note=pevent.title,
                )
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "past_event", "block": blockers.keys()},
                )
        return ret

    @access("persona")
    def list_past_courses(
        self, rs: RequestState, pevent_id: Optional[int] = None
    ) -> dict[int, str]:
        """List all relevant past courses.

        If a `pevent_id` is given, list only courses from a concluded event,
        otherwise, return the full list.

        :returns: Mapping of course ids to titles.
        """
        pevent_id = affirm(vtypes.ID | None, pevent_id)
        if pevent_id:
            data = self.sql_select(
                rs,
                "past_event.courses",
                ("id", "title"),
                (pevent_id,),
                entity_key="pevent_id",
            )
        else:
            query = "SELECT id, title FROM past_event.courses"
            data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde", "event")
    def get_past_courses(
        self, rs: RequestState, pcourse_ids: Collection[int]
    ) -> CdEDataclassMap[models.PastCourse]:
        """Retrieve data for some concluded courses.

        They do not need to be associated to the same event.
        """
        pcourse_ids = affirm(set[vtypes.ID], pcourse_ids)
        pevent_ids = {
            e["pevent_id"]
            for e in self.sql_select(
                rs, models.PastCourse.database_table, ["pevent_id"], pcourse_ids
            )
        }
        pevents = self.get_past_events(rs, pevent_ids)
        ret = models.PastCourse.many_from_database(
            self.query_all(rs, *models.PastCourse.get_select_query(pcourse_ids))
        )
        for pcourse in ret.values():
            pcourse.pevent = pevents[pcourse.pevent_id]
        return ret

    class _GetPastCourseProtocol(Protocol):
        def __call__(self, rs: RequestState, pcourse_id: int) -> models.PastCourse: ...

    get_past_course: _GetPastCourseProtocol = singularize(
        get_past_courses, "pcourse_ids", "pcourse_id"
    )

    @access("cde_admin", "event_admin")
    def set_past_course(self, rs: RequestState, data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of a concluded course."""
        data = affirm(models.PastCourse, data)
        with Atomizer(rs):
            ret = self.sql_update(rs, models.PastCourse.database_table, data)
            current = self.get_past_course(rs, data['id'])
            self.past_event_log(
                rs,
                code=const.PastEventLogCodes.course_changed,
                pevent_id=current.pevent_id,
                pcourse_id=current.id,
            )
        return ret

    @access("cde_admin", "event_admin")
    def create_past_course(
        self, rs: RequestState, data: CdEDBObject
    ) -> DefaultReturnCode:
        """Make a new concluded course."""
        data = affirm(models.PastCourse, data, creation=True)
        with Atomizer(rs):
            ret = self.sql_insert(rs, models.PastCourse.database_table, data)
            self.past_event_log(
                rs,
                code=const.PastEventLogCodes.course_created,
                pevent_id=data['pevent_id'],
                pcourse_id=ret,
            )
        return ret

    @access("cde_admin")
    def delete_past_course_blockers(
        self, rs: RequestState, pcourse_id: int
    ) -> DeletionBlockers:
        """Determine what keeps a past course from being deleted.

        Possible blockers:

        * participants: Participants of the past course.
        * genesis cases: A genesis case associated with this past course.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        pcourse_id = affirm(vtypes.ID, pcourse_id)
        blockers: DeletionBlockers = {}

        count, participants = self.get_course_assignments(rs, pcourse_id)
        if count != len(participants):
            raise RuntimeError("Impossible.")
        if participants:
            blockers["participants"] = [e.id for e in participants.values()]
        log = self.sql_select(
            rs, "past_event.log", ("id",), (pcourse_id,), entity_key="pcourse_id"
        )
        if log:
            blockers["log"] = [e["id"] for e in log]
        genesis_cases = self.sql_select(
            rs, "core.genesis_cases", ("id",), (pcourse_id,), entity_key="pcourse_id"
        )
        if genesis_cases:
            blockers["genesis_cases"] = [e["id"] for e in genesis_cases]

        return blockers

    @access("cde_admin")
    def delete_past_course(
        self,
        rs: RequestState,
        pcourse_id: int,
        cascade: Optional[Collection[str]] = None,
    ) -> DefaultReturnCode:
        """Remove past course.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        pcourse_id = affirm(vtypes.ID, pcourse_id)
        blockers = self.delete_past_course_blockers(rs, pcourse_id)
        if not cascade:
            cascade = set()
        cascade = affirm(set[str], cascade)
        cascade &= blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(
                n_("Deletion of %(type)s blocked by %(block)s."),
                {
                    "type": "past_course",
                    "block": blockers.keys() - cascade,
                },
            )

        ret = 1
        with Atomizer(rs):
            pcourse = self.get_past_course(rs, pcourse_id)
            if cascade:
                if "participants" in cascade:
                    ret *= self.sql_delete(
                        rs, "past_event.course_participants", blockers["participants"]
                    )
                if "log" in cascade:
                    ret *= self.sql_delete(rs, "past_event.log", blockers["log"])
                if "genesis_cases" in cascade:
                    for case_id in blockers["genesis_cases"]:
                        # we use sql_update instead of core.modify_genesis_case here,
                        #  since the latter is forbidden for finalized cases
                        update = {'id': case_id, 'pcourse_id': None}
                        ret *= self.sql_update(rs, "core.genesis_cases", update)

                blockers = self.delete_past_course_blockers(rs, pcourse_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "past_event.courses", pcourse_id)
                self.past_event_log(
                    rs,
                    code=const.PastEventLogCodes.course_deleted,
                    pevent_id=pcourse.pevent_id,
                    change_note=pcourse.title,
                )
        return ret

    @access("core_admin", "cde_admin", "event_admin")
    def set_participant(
        self,
        rs: RequestState,
        pevent_id: int,
        persona_id: int,
        orga_status: const.PastOrgaKind = const.PastOrgaKind.none,
        music_status: const.PastMusicKind = const.PastMusicKind.none,
    ) -> DefaultReturnCode:
        """Mark a persona as participant of a concluded event."""
        pevent_id = affirm(vtypes.ID, pevent_id)
        persona_id = affirm(vtypes.ID, persona_id)
        orga_status = affirm(const.PastOrgaKind, orga_status)
        music_status = affirm(const.PastMusicKind, music_status)
        with Atomizer(rs):
            # Validate data consistency
            if not self.core.verify_persona(rs, persona_id, {"event"}):
                raise ValueError(n_("This past event participant is no event user."))

            data = {
                "pevent_id": pevent_id,
                "persona_id": persona_id,
                "orga_status": orga_status,
                "music_status": music_status,
            }
            ret = self.sql_insert(
                rs,
                "past_event.participants",
                data,
                update_on_conflict=True,
                conflict_target="pevent_id, persona_id",
            )
            relevant_status = []
            if orga_status:
                relevant_status.append(rs.log_gettext(str(orga_status)))
            if music_status:
                relevant_status.append(rs.log_gettext(str(music_status)))
            if ret:
                self.past_event_log(
                    rs,
                    code=const.PastEventLogCodes.participant_set,
                    pevent_id=pevent_id,
                    persona_id=persona_id,
                    change_note=", ".join(relevant_status) or None,
                )
        return ret

    @access("event")
    def is_participant(self, rs: RequestState, pevent_id: int, persona_id: int) -> bool:
        pevent_id = affirm(vtypes.ID, pevent_id)
        persona_id = affirm(vtypes.ID, persona_id)
        return bool(self.get_participant_id(rs, pevent_id, persona_id))

    @internal
    def get_participant_id(
        self, rs: RequestState, pevent_id: int, persona_id: int
    ) -> int | None:
        query = """
            SELECT id
            FROM past_event.participants
            WHERE pevent_id = %(pevent_id)s AND persona_id = %(persona_id)s
        """
        params: ParamDict = {"pevent_id": pevent_id, "persona_id": persona_id}
        return unwrap(self.query_one(rs, query, params))

    @access("core_admin", "cde_admin", "event_admin")
    def set_course_assignments(
        self,
        rs: RequestState,
        pcourse_id: int,
        persona_id: int,
        instructor_status: const.PastInstructorKind = const.PastInstructorKind.none,
    ) -> DefaultReturnCode:
        """Mark a persona as participant of a concluded course."""
        persona_id = affirm(vtypes.ID, persona_id)
        pcourse_id = affirm(vtypes.ID, pcourse_id)
        instructor_status = affirm(const.PastInstructorKind, instructor_status)
        with Atomizer(rs):
            # Validate data consistency
            if not self.core.verify_persona(rs, persona_id, {"event"}):
                raise ValueError(n_("This past event participant is no event user."))

            pevent_id: int = unwrap(  # type: ignore[assignment]
                self.sql_select_one(rs, "past_event.courses", ["pevent_id"], pcourse_id)
            )
            ret = 1
            participant_id = self.get_participant_id(rs, pevent_id, persona_id)
            if participant_id is None:
                raise ValueError(n_("This user does not participate at this event."))

            data = {
                'pcourse_id': pcourse_id,
                'participant_id': participant_id,
                'instructor_status': instructor_status,
            }
            ret *= self.sql_insert(
                rs,
                "past_event.course_participants",
                data,
                update_on_conflict=True,
                conflict_target="pcourse_id, participant_id",
            )
            relevant_status = []
            if instructor_status:
                relevant_status.append(rs.log_gettext(str(instructor_status)))
            if ret:
                self.past_event_log(
                    rs,
                    code=const.PastEventLogCodes.course_assignment_set,
                    pevent_id=pevent_id,
                    pcourse_id=pcourse_id,
                    persona_id=persona_id,
                    change_note=",".join(relevant_status) or None,
                )
        return ret

    @access("core_admin", "cde_admin", "event_admin")
    def remove_participant(
        self,
        rs: RequestState,
        pevent_id: int,
        persona_id: int,
    ) -> DefaultReturnCode:
        """Remove a participant from a concluded event.

        Also removes the participant from all courses of the concluded event.
        """
        pevent_id = affirm(vtypes.ID, pevent_id)
        persona_id = affirm(vtypes.ID, persona_id)
        ret = 1
        with Atomizer(rs):
            # remove manually from courses to ensure correct logging
            _, participants = self.list_event_participants(rs, pevent_id)
            if participant := participants.get(persona_id):
                for assignment in participant.course_assignments:
                    ret *= self.remove_course_assignment(
                        rs, assignment.pcourse_id, persona_id
                    )

            query = """
                DELETE FROM past_event.participants
                WHERE pevent_id = %(pevent_id)s AND persona_id = %(persona_id)s
            """
            params: ParamDict = {"pevent_id": pevent_id, "persona_id": persona_id}
            ret = self.query_exec(rs, query, params)
            self.past_event_log(
                rs,
                code=const.PastEventLogCodes.participant_removed,
                pevent_id=pevent_id,
                persona_id=persona_id,
            )
        return ret

    @access("core_admin", "cde_admin", "event_admin")
    def remove_course_assignment(
        self,
        rs: RequestState,
        pcourse_id: int,
        persona_id: int,
    ) -> DefaultReturnCode:
        """Remove a participant from a course of a concluded event."""
        pcourse_id = affirm(vtypes.ID, pcourse_id)
        persona_id = affirm(vtypes.ID, persona_id)
        with Atomizer(rs):
            pevent_id: int = unwrap(  # type: ignore[assignment]
                self.sql_select_one(rs, "past_event.courses", ["pevent_id"], pcourse_id)
            )
            participant_id = self.get_participant_id(rs, pevent_id, persona_id)
            # nothing left to do
            if participant_id is None:
                return 0

            query = """
                DELETE FROM past_event.course_participants
                WHERE pcourse_id = %(pcourse_id)s AND participant_id = %(participant_id)s
            """
            params: ParamDict = {
                "pcourse_id": pcourse_id,
                "participant_id": participant_id,
            }
            ret = self.query_exec(rs, query, params)
            self.past_event_log(
                rs,
                code=const.PastEventLogCodes.course_assignment_removed,
                pevent_id=pevent_id,
                pcourse_id=pcourse_id,
                persona_id=persona_id,
            )
        return ret

    @internal
    def filter_participants(
        self,
        rs: RequestState,
        participants: CdEDataclassMap[T],
        personas: CdEDataclassMap[models_core.PersonaStatus],
        honor_admins: bool,
        pevent_id: int | None = None,
        pcourse_id: int | None = None,
    ) -> CdEDataclassMap[T]:
        """Filter participants based on the privileges of the requesting user.

        Participants are removed from the result if they are not searchable and the
        viewing user is neither admin nor participant of the past event themselves.
        """
        participants = copy.deepcopy(participants)
        if pevent_id is None and pcourse_id is None:
            raise ValueError("Either provide pevent_id or pcourse_id.")
        if rs.user.persona_id is None:
            raise RuntimeError

        # admins may view all participants
        if self.is_admin(rs) and honor_admins:
            return participants

        # next, check if the requesting user participated at the past event
        if pevent_id is None:
            assert pcourse_id is not None
            pevent_id = unwrap(
                self.sql_select_one(rs, "past_event.courses", ["pevent_id"], pcourse_id)
            )
        assert pevent_id is not None
        if self.is_participant(rs, pevent_id, rs.user.persona_id):
            return participants

        # if the user is neither admin nor participant, we filter the data
        if "searchable" in rs.user.roles:
            for persona in personas.values():
                if not persona.is_member or not persona.is_searchable:
                    del participants[persona.id]
            return participants
        return {}

    @access("event")
    def list_event_participants(
        self,
        rs: RequestState,
        pevent_id: int,
        honor_admins: bool = True,
    ) -> tuple[int, CdEDataclassMap[models.PastEventParticipant]]:
        """List all participants of a concluded event.

        Participants are removed from the result if they are not searchable and the
        viewing user is neither admin nor participant of the past event themselves.

        :param honor_admins: if False, ignore admin privileges in privilege check.
        :returns: The total number of participants, and a dict of the participants
            which are accessible by this user.
        """
        pevent_id = affirm(vtypes.ID, pevent_id)
        honor_admins = affirm(bool, honor_admins)

        # collect past event data
        data = self.sql_select(
            rs,
            models.PastEventParticipant.database_table,
            models.PastEventParticipant.database_fields(),
            [pevent_id],
            entity_key="pevent_id",
        )
        total_participants_num = len(data)
        personas = self.core.get_core_users(rs, {e['persona_id'] for e in data})
        pevent = self.get_past_event(rs, pevent_id)
        for datum in data:
            datum["persona"] = personas[datum["persona_id"]]
            datum["pevent"] = pevent
        ret = models.PastEventParticipant.many_from_database(data)
        ret = {participant.persona_id: participant for participant in ret.values()}

        # collect past course data
        query = f"""
            SELECT course_assignments.id, persona_id, instructor_status, pcourse_id, participant_id
            FROM {models.PastEventParticipant.database_table} AS event_participants
                JOIN {models.PastCourseAssignment.database_table} AS course_assignments
                ON participant_id = event_participants.id
            WHERE pevent_id = %(pevent_id)s
        """
        data = self.query_all(rs, query, {"pevent_id": pevent_id})
        pcourses = self.get_past_courses(rs, {e["pcourse_id"] for e in data})
        for datum in data:
            datum["pcourse"] = pcourses[datum["pcourse_id"]]
        course_assignments = models.PastCourseAssignment.many_from_database(data)
        for assignment in course_assignments.values():
            ret[assignment.persona_id].course_assignments.append(assignment)

        # filter the data
        ret = self.filter_participants(
            rs,
            participants=ret,  # type: ignore[arg-type]
            personas=self.core.get_personas_status(rs, personas.keys()),
            honor_admins=honor_admins,
            pevent_id=pevent_id,
        )

        return total_participants_num, ret

    @access("event")
    def get_course_assignments(
        self, rs: RequestState, pcourse_id: int, honor_admins: bool = True
    ) -> tuple[int, CdEDataclassMap[models.PastCourseAssignment]]:
        """List all participants of the given concluded course.

        Participants are removed from the result if they are not searchable and the
        viewing user is neither admin nor participant of the past event themselves.

        :param honor_admins: if False, ignore admin privileges in privilege check.
        :returns: The total number of participants, and a dict mapping persona_ids to
            their course assignment, if they are accessible by this user.
        """
        pcourse_id = affirm(vtypes.ID, pcourse_id)
        honor_admins = affirm(bool, honor_admins)
        query = f"""
            SELECT course_assignments.id, persona_id, instructor_status, pcourse_id, participant_id
            FROM {models.PastEventParticipant.database_table} AS event_participants
                JOIN {models.PastCourseAssignment.database_table} AS course_assignments
                ON participant_id = event_participants.id
            WHERE pcourse_id = %(pcourse_id)s
        """
        params: ParamDict = {"pcourse_id": pcourse_id}
        data = self.query_all(rs, query, params)
        personas = self.core.get_core_users(rs, {e['persona_id'] for e in data})
        pcourse = self.get_past_course(rs, pcourse_id)
        for datum in data:
            datum["pcourse"] = pcourse
        ret = models.PastCourseAssignment.many_from_database(data)
        ret = {
            assignment.persona_id: assignment
            for assignment in xsorted(
                ret.values(), key=lambda x: personas[x.persona_id]
            )
        }
        ret = self.filter_participants(
            rs,
            participants=ret,  # type: ignore[arg-type]
            personas=self.core.get_personas_status(rs, personas.keys()),
            honor_admins=honor_admins,
            pcourse_id=pcourse_id,
        )

        return len(data), ret

    @access("event")
    def list_persona_events(
        self,
        rs: RequestState,
        persona_id: int,
    ) -> CdEDataclassMap[models.PastEventParticipant]:
        """List all past events of the given persona."""
        persona_id = affirm(vtypes.ID, persona_id)
        persona_status = self.core.get_persona_status(rs, persona_id)
        if not (
            self.is_admin(rs)
            or "core_admin" in rs.user.roles
            or persona_id == rs.user.persona_id
            or (
                "searchable" in rs.user.roles
                and persona_status.is_member
                and persona_status.is_searchable
            )
        ):
            raise PrivilegeError

        # collect past event data
        data = self.sql_select(
            rs,
            models.PastEventParticipant.database_table,
            models.PastEventParticipant.database_fields(),
            [persona_id],
            entity_key="persona_id",
        )
        pevents = self.get_past_events(rs, {datum["pevent_id"] for datum in data})
        for datum in data:
            datum["persona"] = self.core.get_core_user(rs, persona_id)
            datum["pevent"] = pevents[datum["pevent_id"]]
        ret = models.PastEventParticipant.many_from_database(data)
        ret = {p.pevent_id: p for p in ret.values()}

        # collect past course data
        query = f"""
            SELECT course_assignments.id, persona_id, participant_id, pcourse_id, instructor_status
            FROM {models.PastEventParticipant.database_table} AS event_participants
                JOIN {models.PastCourseAssignment.database_table} AS course_assignments
                ON participant_id = event_participants.id
            WHERE persona_id = %(persona_id)s
        """
        data = self.query_all(rs, query, {"persona_id": persona_id})
        pcourses = self.get_past_courses(rs, {datum["pcourse_id"] for datum in data})
        for datum in data:
            datum["pcourse"] = pcourses[datum["pcourse_id"]]
        course_assignments = models.PastCourseAssignment.many_from_database(data)
        for assignment in course_assignments.values():
            ret[assignment.pcourse.pevent_id].course_assignments.append(assignment)
        return ret  # type: ignore[return-value]

    @access("cde_admin", "event_admin")
    def find_past_event(
        self, rs: RequestState, shortname: str
    ) -> tuple[Optional[int], list[Error], list[Error]]:
        """Look for events with a certain name.

        This is mainly for batch admission, where we want to
        automatically resolve past events to their ids.

        :returns: The id of the past event or None if there were errors.
        """
        shortname = affirm(str | None, shortname)
        if not shortname:
            return None, [], [("pevent_id", ValueError(n_("No input supplied.")))]
        query = """
            SELECT id FROM past_event.events
            WHERE (title ~* %s OR shortname ~* %s) AND tempus >= %s
        """
        query2 = """
            SELECT id FROM past_event.events
            WHERE similarity(title, %s) > %s AND tempus >= %s
        """
        today = now().date()
        reference = today - datetime.timedelta(days=200)
        reference = reference.replace(day=1, month=1)
        ret = self.query_all(rs, query, (shortname, shortname, reference))
        warnings: list[Error] = []
        # retry with less restrictive conditions until we find something or
        # give up
        if not ret:
            ret = self.query_all(rs, query, (shortname, shortname, datetime.date.min))
        if not ret:
            warnings.append(("pevent_id", ValueError(n_("Only fuzzy match."))))
            ret = self.query_all(rs, query2, (shortname, 0.5, reference))
        if not ret:
            ret = self.query_all(rs, query2, (shortname, 0.5, datetime.date.min))
        if not ret:
            return None, [], [("pevent_id", ValueError(n_("No event found.")))]
        elif len(ret) > 1:
            return None, warnings, [("pevent_id", ValueError(n_("Ambiguous event.")))]
        else:
            return unwrap(unwrap(ret)), warnings, []

    @access("cde_admin", "event_admin")
    def find_past_course(
        self, rs: RequestState, phrase: str, pevent_id: int
    ) -> tuple[Optional[int], list[Error], list[Error]]:
        """Look for courses with a certain number/name.

        This is mainly for batch admission, where we want to
        automatically resolve past courses to their ids.

        :param pevent_id: Restrict to courses of this past event.
        :returns: The id of the past course or None if there were errors.
        """
        phrase = affirm(str | None, phrase)
        if not phrase:
            return None, [], [("pcourse_id", ValueError(n_("No input supplied.")))]
        pevent_id = affirm(vtypes.ID, pevent_id)
        query = "SELECT id FROM past_event.courses WHERE pevent_id = %s"
        q1 = query + " AND nr = %s"
        q2 = query + " AND title ~* %s"
        q3 = query + " AND similarity(title, %s) > %s"
        params: tuple[Any, ...] = (pevent_id, phrase)
        ret = self.query_all(rs, q1, params)
        warnings: list[Error] = []
        # retry with less restrictive conditions until we find something or
        # give up
        if not ret:
            warnings.append(("pcourse_id", ValueError(n_("Only title match."))))
            ret = self.query_all(rs, q2, params)
        if not ret:
            warnings.append(("pcourse_id", ValueError(n_("Only fuzzy match."))))
            ret = self.query_all(rs, q3, params + (0.5,))
        if not ret:
            return None, [], [("pcourse_id", ValueError(n_("No course found.")))]
        elif len(ret) > 1:
            return None, warnings, [("pcourse_id", ValueError(n_("Ambiguous course.")))]
        else:
            return unwrap(unwrap(ret)), warnings, []

    def archive_one_part(
        self, rs: RequestState, event: models_event.Event, part_id: int
    ) -> DefaultReturnCode:
        """Uninlined code from :py:meth:`archive_event`

        This assumes implicit atomization by the caller.

        :returns: ID of the newly created past event.
        """
        part = event.parts[part_id]
        pevent = models.PastEvent.from_event(event, part_id)
        new_id = self.create_past_event(rs, pevent.to_database())

        course_ids = self.event.list_courses(rs, event.id)
        courses = self.event.get_courses(rs, list(course_ids.keys()))
        course_map: dict[int, int] = {}
        for course in courses.values():
            # do not create courses which didn't took place at this event part
            if not course.active_segments & set(part.tracks):
                continue
            pcourse = models.PastCourse.from_course(course, pevent_id=new_id)
            pcourse_id = self.create_past_course(rs, pcourse.to_database())
            course_map[course.id] = pcourse_id

        reg_ids = self.event.list_registrations(rs, event.id)
        regs = self.event.get_registrations(rs, list(reg_ids.keys()))

        # maps persona_ids to their dicts of courses, the bool signals instructorship
        participants_to_courses: dict[int, dict[int, bool]] = {}
        for reg in regs.values():
            participant_status = const.RegistrationPartStati.participant
            if reg['parts'][part_id]['status'] != participant_status:
                continue
            participants_to_courses[reg['persona_id']] = collections.defaultdict(bool)
            for track_id in part.tracks:
                if course_id := reg['tracks'][track_id]['course_id']:
                    if course_id == reg['tracks'][track_id]['course_instructor']:
                        participants_to_courses[reg['persona_id']][course_id] = True
                    # Take care to not overwrite the instructor state when the course
                    #  is present in multiple tracks of this part.
                    participants_to_courses[reg['persona_id']].setdefault(
                        course_id, False
                    )

        # now add the participants to the past event
        for persona_id, course_ids in participants_to_courses.items():
            orga_status = const.PastOrgaKind.none
            if persona_id in event.orgas:
                orga_status = const.PastOrgaKind.orga
            self.set_participant(rs, new_id, persona_id, orga_status=orga_status)
            for course_id, is_instructor in course_ids.items():
                if not courses[course_id].active_segments & set(part.tracks):
                    self.logger.warning(
                        f"During archival of event {event.id}, persona {persona_id}"
                        f" participated in cancelled course {course_id} in part {part.id}."
                    )
                    continue
                instructor_status = const.PastInstructorKind.none
                if is_instructor:
                    instructor_status = const.PastInstructorKind.kl
                self.set_course_assignments(
                    rs, course_map[course_id], persona_id, instructor_status
                )

        # Delete past event if it has no participants.
        if not participants_to_courses:
            self.delete_past_event(rs, new_id, cascade=("log",))
            return 0

        return new_id

    @access("cde_admin", "event_admin")
    def archive_event(
        self, rs: RequestState, event_id: int, create_past_event: bool = True
    ) -> list[int] | None:
        """Archive a concluded event.

        This optionally creates a follow-up past event by transferring data from
        the event into the past event schema.

        The data of the event organization is scheduled to be deleted at
        some point. We retain in the past_event schema only the
        participation information. This automates the process of converting
        data from one schema to the other.

        We export each event part into a separate past event since
        semantically the event parts mostly behave like separate events
        which happen to take place consecutively.

        :returns: The first entry are the ids of the new past events or None
          if there were complications or create_past_events is False.
          If there were complications, the second entry is an error message.
        """
        event_id = affirm(vtypes.ID, event_id)
        if "cde_admin" not in rs.user.roles or "event_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Needs both admin privileges."))
        with Atomizer(rs):
            event = self.event.get_event(rs, event_id)
            if not event.is_cancelled and event.end >= now().date():
                raise ValueError(n_("Event is not concluded yet."))
            self.event.set_event_archived(rs, event_id)
            new_ids = None
            if create_past_event:
                new_ids = []
                for part_id in xsorted(event.parts):
                    new_id = self.archive_one_part(rs, event, part_id)
                    if new_id:
                        new_ids.append(new_id)
                if not new_ids:
                    raise ValueError(n_("No event parts have any participants."))
        return new_ids

    @access("member", "cde_admin")
    def submit_general_query(
        self, rs: RequestState, query: Query, aggregate: bool = False
    ) -> tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        aggregate = affirm(bool, aggregate)
        if query.scope == QueryScope.past_event_course:
            pass
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query, aggregate=aggregate)
