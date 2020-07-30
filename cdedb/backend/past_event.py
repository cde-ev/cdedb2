#!/usr/bin/env python3

"""The past event backend provides means to catalogue information about
concluded events.
"""

import datetime

from typing import (
    Collection, Dict, Callable, Optional, Tuple, Union, List, Set
)

from cdedb.backend.common import (
    access, affirm_validation as affirm, Silencer, AbstractBackend,
    affirm_set_validation as affirm_set, singularize)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    n_, glue, PAST_EVENT_FIELDS, PAST_COURSE_FIELDS, PrivilegeError,
    unwrap, now, make_proxy, INSTITUTION_FIELDS, xsorted, PathLike,
    RequestState, CdEDBObject, CdEDBObjectMap, CdEDBLog, DefaultReturnCode,
    DeletionBlockers, Error
)
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const


class PastEventBackend(AbstractBackend):
    """Handle concluded events.

    This is somewhere between CdE and event realm, so we split it into
    its own realm.
    """
    realm = "past_event"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)
        self.event = make_proxy(EventBackend(configpath), internal=True)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("cde", "event")
    def participation_infos(self, rs: RequestState, ids: Collection[int]
                            ) -> Dict[int, CdEDBObjectMap]:
        """List concluded events visited by specific personas.

        :returns: First keys are the ids, second are the pevent_ids.
        """
        ids = affirm_set("id", ids)
        query = glue(
            "SELECT p.persona_id, e.id, e.title, e.tempus, p.is_orga",
            "FROM past_event.participants AS p",
            "INNER JOIN past_event.events AS e ON (p.pevent_id = e.id)",
            "WHERE p.persona_id = ANY(%s)")
        pevents = self.query_all(rs, query, (ids,))
        query = glue(
            "SELECT p.persona_id, c.id, c.pevent_id, c.title, c.nr,",
            "p.is_instructor",
            "FROM past_event.participants AS p",
            "LEFT OUTER JOIN past_event.courses AS c ON (p.pcourse_id = c.id)",
            "WHERE p.persona_id = ANY(%s)")
        pcourse = self.query_all(rs, query, (ids,))
        ret = {}
        course_fields = ('id', 'title', 'is_instructor', 'nr')
        for pevent in pevents:
            pevent['courses'] = {
                c['id']: {k: c[k] for k in course_fields}
                for c in pcourse if (c['persona_id'] == pevent['persona_id']
                                     and c['pevent_id'] == pevent['id'])
            }
        for anid in ids:
            ret[anid] = {x['id']: x for x in pevents if x['persona_id'] == anid}
        return ret
    participation_info: Callable[[RequestState, int], CdEDBObjectMap]
    participation_info = singularize(participation_infos)

    def past_event_log(self, rs: RequestState, code: const.PastEventLogCodes,
                       pevent_id: Optional[int], persona_id: int = None,
                       additional_info: str = None) -> int:
        """Make an entry in the log for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        if rs.is_quiet:
            return 0
        data = {
            "code": code,
            "pevent_id": pevent_id,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,
        }
        return self.sql_insert(rs, "past_event.log", data)

    @access("cde_admin", "event_admin")
    def retrieve_past_log(self, rs: RequestState,
                          codes: Collection[const.PastEventLogCodes] = None,
                          pevent_id: int = None, offset: int = None,
                          length: int = None, persona_id: int = None,
                          submitted_by: int = None, additional_info: str = None,
                          time_start: datetime.datetime = None,
                          time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get recorded activity for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        pevent_id = affirm("id_or_None", pevent_id)
        pevent_ids = [pevent_id] if pevent_id else None
        return self.generic_retrieve_log(
            rs, "enum_pasteventlogcodes", "pevent", "past_event.log",
            codes=codes, entity_ids=pevent_ids, offset=offset, length=length,
            persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info, time_start=time_start,
            time_stop=time_stop)

    @access("cde", "event")
    def list_institutions(self, rs: RequestState) -> Dict[int, str]:
        """List all institutions.

        :returns: Mapping of institution ids to titles.
        """
        query = "SELECT id, title FROM past_event.institutions"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde", "event")
    def get_institutions(self, rs: RequestState, ids: Collection[int]
                         ) -> CdEDBObjectMap:
        """Retrieve data for some institutions."""
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.institutions",
                               INSTITUTION_FIELDS, ids)
        return {e['id']: e for e in data}
    get_institution: Callable[['PastEventBackend', RequestState, int],
                              CdEDBObject]
    get_institution = singularize(get_institutions)

    @access("cde_admin", "event_admin")
    def set_institution(self, rs: RequestState, data: CdEDBObject
                        ) -> DefaultReturnCode:
        """Update some keys of an institution."""
        data = affirm("institution", data)
        ret = self.sql_update(rs, "past_event.institutions", data)
        current = unwrap(self.get_institutions(rs, (data['id'],)))
        self.past_event_log(rs, const.PastEventLogCodes.institution_changed,
                            pevent_id=None, additional_info=current['title'])
        return ret

    @access("cde_admin", "event_admin")
    def create_institution(self, rs: RequestState, data: CdEDBObject
                           ) -> DefaultReturnCode:
        """Make a new institution."""
        data = affirm("institution", data, creation=True)
        ret = self.sql_insert(rs, "past_event.institutions", data)
        self.past_event_log(rs, const.PastEventLogCodes.institution_created,
                            pevent_id=None, additional_info=data['title'])
        return ret

    # TODO: rework deletion interface
    @access("cde_admin", "event_admin")
    def delete_institution(self, rs: RequestState, institution_id: int,
                           cascade: bool = False) -> DefaultReturnCode:
        """Remove an institution

        The institution may not be referenced.

        :param cascade: Must be False.
        """
        institution_id = affirm("id", institution_id)
        cascade = affirm("bool", cascade)
        if cascade:
            raise NotImplementedError(n_("Not available."))

        current = unwrap(self.get_institutions(rs, (institution_id,)))
        with Atomizer(rs):
            ret = self.sql_delete_one(rs, "past_event.institutions",
                                      institution_id)
            self.past_event_log(
                rs, const.PastEventLogCodes.institution_deleted,
                pevent_id=None, additional_info=current['title'])
        return ret

    @access("persona")
    def list_past_events(self, rs: RequestState) -> Dict[int, str]:
        """List all concluded events.

        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM past_event.events"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde")
    def past_event_stats(self, rs: RequestState) -> CdEDBObjectMap:
        """Additional information about concluded events.

        This is mostly an extended version of the listing function which
        provides aggregate data without the need to shuttle the complete
        table to the frontend.

        :returns: Mapping of event ids to stats.
        """
        query = """
        SELECT
            events.id AS pevent_id, tempus, institutions.id AS institution_id,
            institutions.moniker AS institution_moniker, 
            COALESCE(course_count, 0) AS courses, 
            COALESCE(participant_count, 0) AS participants
        FROM (
            past_event.events
            LEFT OUTER JOIN
                past_event.institutions
            ON institutions.id = events.institution
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
        )"""
        data = self.query_all(rs, query, tuple())
        ret = {e['pevent_id']: e for e in data}
        return ret

    @access("cde", "event")
    def get_past_events(self, rs: RequestState, ids: Collection[int]
                        ) -> CdEDBObjectMap:
        """Retrieve data for some concluded events."""
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.events", PAST_EVENT_FIELDS, ids)
        return {e['id']: e for e in data}
    get_past_event: Callable[
        ['PastEventBackend', RequestState, int], CdEDBObject]
    get_past_event = singularize(get_past_events)

    @access("cde_admin", "event_admin")
    def set_past_event(self, rs: RequestState, data: CdEDBObject
                       ) -> DefaultReturnCode:
        """Update some keys of a concluded event."""
        data = affirm("past_event", data)
        ret = self.sql_update(rs, "past_event.events", data)
        self.past_event_log(rs, const.PastEventLogCodes.event_changed,
                            data['id'])
        return ret

    @access("cde_admin", "event_admin")
    def create_past_event(self, rs: RequestState, data: CdEDBObject
                          ) -> DefaultReturnCode:
        """Make a new concluded event."""
        data = affirm("past_event", data, creation=True)
        ret = self.sql_insert(rs, "past_event.events", data)
        self.past_event_log(rs, const.PastEventLogCodes.event_created, ret)
        return ret

    @access("cde_admin")
    def delete_past_event_blockers(self, rs: RequestState, pevent_id: int
                                   ) -> DeletionBlockers:
        """Determine what keeps a past event from being deleted.

        Possible blockers:

        * participants: A participant of the past event or one of its
                        courses.
        * courses: A course associated with the past event.
        * log: A log entry for the past event.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        pevent_id = affirm("id", pevent_id)
        blockers = {}

        participants = self.sql_select(rs, "past_event.participants", ("id",),
                                       (pevent_id,), entity_key="pevent_id")
        if participants:
            blockers["participants"] = [e["id"] for e in participants]

        courses = self.sql_select(rs, "past_event.courses", ("id",),
                                  (pevent_id,), entity_key="pevent_id")
        if courses:
            blockers["courses"] = [e["id"] for e in courses]

        log = self.sql_select(rs, "past_event.log", ("id",), (pevent_id,),
                              entity_key="pevent_id")
        if log:
            blockers["log"] = [e["id"] for e in log]

        return blockers

    @access("cde_admin")
    def delete_past_event(self, rs: RequestState, pevent_id: int,
                          cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove past event.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """

        pevent_id = affirm("id", pevent_id)
        blockers = self.delete_past_event_blockers(rs, pevent_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "past_event",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            pevent = self.get_past_event(rs, pevent_id)
            if cascade:
                if "participants" in cascade:
                    ret *= self.sql_delete(
                        rs, "past_event.participants", blockers["participants"])
                if "courses" in cascade:
                    with Silencer(rs):
                        for pcourse_id in blockers["courses"]:
                            ret *= self.delete_past_course(
                                rs, pcourse_id, ("participants",))
                if "log" in cascade:
                    ret *= self.sql_delete(
                        rs, "past_event.log", blockers["log"])

                blockers = self.delete_past_event_blockers(rs, pevent_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "past_event.events", pevent_id)
                self.past_event_log(rs, const.PastEventLogCodes.event_deleted,
                                    pevent_id=None, persona_id=None,
                                    additional_info=pevent['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "past_event", "block": blockers.keys()})
        return ret

    @access("persona")
    def list_past_courses(self, rs: RequestState, pevent_id: int
                          ) -> Dict[int, str]:
        """List all courses of a concluded event.

        :returns: Mapping of course ids to titles.
        """
        pevent_id = affirm("id", pevent_id)
        data = self.sql_select(rs, "past_event.courses", ("id", "title"),
                               (pevent_id,), entity_key="pevent_id")
        return {e['id']: e['title'] for e in data}

    @access("cde", "event")
    def get_past_courses(self, rs: RequestState, ids: Collection[int]
                         ) -> CdEDBObjectMap:
        """Retrieve data for some concluded courses.

        They do not need to be associated to the same event.
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.courses", PAST_COURSE_FIELDS,
                               ids)
        return {e['id']: e for e in data}
    get_past_course: Callable[
        ['PastEventBackend', RequestState, int], CdEDBObject]
    get_past_course = singularize(get_past_courses)

    @access("cde_admin", "event_admin")
    def set_past_course(self, rs: RequestState, data: CdEDBObject
                        ) -> DefaultReturnCode:
        """Update some keys of a concluded course."""
        data = affirm("past_course", data)
        current = self.sql_select_one(rs, "past_event.courses",
                                      ("title", "pevent_id"), data['id'])
        # TODO do more checking here?
        if current is None:
            raise ValueError(n_("Referenced past course does not exist."))
        ret = self.sql_update(rs, "past_event.courses", data)
        current.update(data)
        self.past_event_log(
            rs, const.PastEventLogCodes.course_changed, current['pevent_id'],
            additional_info=current['title'])
        return ret

    @access("cde_admin", "event_admin")
    def create_past_course(self, rs: RequestState, data: CdEDBObject
                           ) -> DefaultReturnCode:
        """Make a new concluded course."""
        data = affirm("past_course", data, creation=True)
        ret = self.sql_insert(rs, "past_event.courses", data)
        self.past_event_log(rs, const.PastEventLogCodes.course_created,
                            data['pevent_id'], additional_info=data['title'])
        return ret

    @access("cde_admin")
    def delete_past_course_blockers(self, rs: RequestState, pcourse_id: int
                                    ) -> DeletionBlockers:
        """Determine what keeps a past course from being deleted.

        Possible blockers:

        * participants: Participants of the past course.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        pcourse_id = affirm("id", pcourse_id)
        blockers = {}

        participants = self.sql_select(rs, "past_event.participants", ("id",),
                                       (pcourse_id,), entity_key="pcourse_id")
        if participants:
            blockers["participants"] = [e["id"] for e in participants]

        return blockers

    @access("cde_admin")
    def delete_past_course(self, rs: RequestState, pcourse_id: int,
                           cascade: Collection[str] = None
                           ) -> DefaultReturnCode:
        """Remove past course.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        pcourse_id = affirm("id", pcourse_id)
        blockers = self.delete_past_course_blockers(rs, pcourse_id)
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade)
        cascade = cascade & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "past_course",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            pcourse = self.get_past_course(rs, pcourse_id)
            if cascade:
                if "participants" in cascade:
                    ret *= self.sql_delete(
                        rs, "past_event.participants", blockers["participants"])

                blockers = self.delete_past_course_blockers(rs, pcourse_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "past_event.courses", pcourse_id)
                self.past_event_log(
                    rs, const.PastEventLogCodes.course_deleted,
                    pcourse['pevent_id'], additional_info=pcourse['title'])
        return ret

    @access("cde_admin", "event_admin")
    def add_participant(self, rs: RequestState, pevent_id: int,
                        pcourse_id: Optional[int], persona_id: int,
                        is_instructor: bool, is_orga: bool
                        ) -> DefaultReturnCode:
        """Add a participant to a concluded event.

        A persona can participate multiple times in a single event. For
        example if she took several courses in different parts of the event.

        :param pcourse_id: If None the persona participated in the event, but
          not in a course (this should be common for orgas).
        """
        data = {'persona_id': affirm("id", persona_id),
                'pevent_id': affirm("id", pevent_id),
                'pcourse_id': affirm("id_or_None", pcourse_id),
                'is_instructor': affirm("bool", is_instructor),
                'is_orga': affirm("bool", is_orga)}
        ret = self.sql_insert(rs, "past_event.participants", data)
        self.past_event_log(
            rs, const.PastEventLogCodes.participant_added, pevent_id,
            persona_id=persona_id)
        return ret

    @access("cde_admin", "event_admin")
    def remove_participant(self, rs: RequestState, pevent_id: int,
                           pcourse_id: Optional[int], persona_id: int
                           ) -> DefaultReturnCode:
        """Remove a participant from a concluded event.

        All attributes have to match exactly, so that if someone
        participated multiple times (for example in different courses) we
        are able to delete an exact instance.
        """
        pevent_id = affirm("id", pevent_id)
        pcourse_id = affirm("id_or_None", pcourse_id)
        persona_id = affirm("id", persona_id)
        query = glue("DELETE FROM past_event.participants WHERE pevent_id = %s",
                     "AND persona_id = %s AND pcourse_id {} %s")
        query = query.format("IS" if pcourse_id is None else "=")
        ret = self.query_exec(rs, query, (pevent_id, persona_id, pcourse_id))
        self.past_event_log(
            rs, const.PastEventLogCodes.participant_removed, pevent_id,
            persona_id=persona_id)
        return ret

    @access("cde", "event")
    def list_participants(self, rs: RequestState, *, pevent_id: int = None,
                          pcourse_id: int = None
                          ) -> Dict[Tuple[int, Optional[int]], CdEDBObject]:
        """List all participants of a concluded event or course.

        Exactly one of the inputs has to be provided.

        .. note:: The return value uses two integers as key, since only the
          persona id is not unique.
        """
        if pevent_id is not None and pcourse_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        elif pevent_id is not None:
            anid = affirm("id", pevent_id)
            entity_key = "pevent_id"
        elif pcourse_id is not None:
            anid = affirm("id", pcourse_id)
            entity_key = "pcourse_id"
        else:  # pevent_id is None and pcourse_id is None:
            raise ValueError(n_("No input specified."))

        data = self.sql_select(
            rs, "past_event.participants",
            ("persona_id", "pcourse_id", "is_instructor", "is_orga"), (anid,),
            entity_key=entity_key)
        return {(e['persona_id'], e['pcourse_id']): e
                for e in data}

    @access("cde_admin", "event_admin")
    def find_past_event(self, rs: RequestState, moniker: str
                        ) -> Tuple[Optional[int], List[Error], List[Error]]:
        """Look for events with a certain name.

        This is mainly for batch admission, where we want to
        automatically resolve past events to their ids.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type moniker: str
        :rtype: (int or None, [exception])
        :returns: The id of the past event or None if there were errors.
        """
        moniker = affirm("str_or_None", moniker)
        if not moniker:
            return None, [], [("pevent_id",
                               ValueError(n_("No input supplied.")))]
        query = glue("SELECT id FROM past_event.events",
                     "WHERE (title ~* %s OR shortname ~* %s) AND tempus >= %s")
        query2 = glue("SELECT id FROM past_event.events",
                      "WHERE similarity(title, %s) > %s AND tempus >= %s")
        today = now().date()
        reference = today - datetime.timedelta(days=200)
        reference = reference.replace(day=1, month=1)
        ret = self.query_all(rs, query, (moniker, moniker, reference))
        warnings: List[Error] = []
        # retry with less restrictive conditions until we find something or
        # give up
        if len(ret) == 0:
            ret = self.query_all(rs, query,
                                 (moniker, moniker, datetime.date.min))
        if len(ret) == 0:
            warnings.append(("pevent_id", ValueError(n_("Only fuzzy match."))))
            ret = self.query_all(rs, query2, (moniker, 0.5, reference))
        if len(ret) == 0:
            ret = self.query_all(rs, query2, (moniker, 0.5, datetime.date.min))
        if len(ret) == 0:
            return None, [], [("pevent_id", ValueError(n_("No event found.")))]
        elif len(ret) > 1:
            return None, warnings, [("pevent_id",
                                     ValueError(n_("Ambiguous event.")))]
        else:
            return unwrap(unwrap(ret)), warnings, []

    @access("cde_admin", "event_admin")
    def find_past_course(self, rs: RequestState, phrase: str, pevent_id: int
                         ) -> Tuple[Optional[int], List[Error], List[Error]]:
        """Look for courses with a certain number/name.

        This is mainly for batch admission, where we want to
        automatically resolve past courses to their ids.

        :param pevent_id: Restrict to courses of this past event.
        :returns: The id of the past course or None if there were errors.
        """
        phrase = affirm("str_or_None", phrase)
        if not phrase:
            return None, [], [("pcourse_id",
                               ValueError(n_("No input supplied.")))]
        pevent_id = affirm("id", pevent_id)
        query = "SELECT id FROM past_event.courses WHERE pevent_id = %s"
        q1 = query + " AND nr = %s"
        q2 = query + " AND title ~* %s"
        q3 = query + " AND similarity(title, %s) > %s"
        params: Tuple = (pevent_id, phrase)
        ret = self.query_all(rs, q1, params)
        warnings: List[Error] = []
        # retry with less restrictive conditions until we find something or
        # give up
        if len(ret) == 0:
            warnings.append(("pcourse_id", ValueError(n_("Only title match."))))
            ret = self.query_all(rs, q2, params)
        if len(ret) == 0:
            warnings.append(("pcourse_id", ValueError(n_("Only fuzzy match."))))
            ret = self.query_all(rs, q3, params + (0.5,))
        if len(ret) == 0:
            return None, [], [
                ("pcourse_id", ValueError(n_("No course found.")))]
        elif len(ret) > 1:
            return None, warnings, [("pcourse_id",
                                     ValueError(n_("Ambiguous course.")))]
        else:
            return unwrap(unwrap(ret)), warnings, []

    def archive_one_part(self, rs: RequestState, event: CdEDBObject,
                         part_id: int) -> DefaultReturnCode:
        """Uninlined code from :py:meth:`archive_event`

        This assumes implicit atomization by the caller.

        :returns: ID of the newly created past event.
        """
        part = event['parts'][part_id]
        pevent = {k: v for k, v in event.items()
                  if k in PAST_EVENT_FIELDS}
        pevent['tempus'] = part['part_begin']
        # The event field 'notes' has nothing to do with the past event
        # field 'notes' -- the first is for orgas and the second for
        # participants
        pevent['notes'] = None
        if len(event['parts']) > 1:
            # Add part designation in case of events with multiple parts
            pevent['title'] += " ({})".format(part['title'])
            pevent['shortname'] += " ({})".format(part['shortname'])
        del pevent['id']
        new_id = self.create_past_event(rs, pevent)
        course_ids = self.event.list_db_courses(rs, event['id'])
        courses = self.event.get_courses(rs, list(course_ids.keys()))
        course_map = {}
        for course_id, course in courses.items():
            pcourse = {k: v for k, v in course.items()
                       if k in PAST_COURSE_FIELDS}
            del pcourse['id']
            pcourse['pevent_id'] = new_id
            pcourse_id = self.create_past_course(rs, pcourse)
            course_map[course_id] = pcourse_id
        reg_ids = self.event.list_registrations(rs, event['id'])
        regs = self.event.get_registrations(rs, list(reg_ids.keys()))
        # we want to later delete empty courses
        courses_seen = set()
        # we want to add each participant/course combination at
        # most once
        combinations_seen: Set[Tuple[int, Optional[int]]] = set()
        for reg in regs.values():
            participant_status = const.RegistrationPartStati.participant
            if reg['parts'][part_id]['status'] != participant_status:
                continue
            is_orga = reg['persona_id'] in event['orgas']
            for track_id, track in part['tracks'].items():
                rtrack = reg['tracks'][track_id]
                is_instructor = False
                if rtrack['course_id']:
                    is_instructor = (rtrack['course_id']
                                     == rtrack['course_instructor'])
                    courses_seen.add(rtrack['course_id'])
                combination = (reg['persona_id'],
                               course_map.get(rtrack['course_id']))
                if combination not in combinations_seen:
                    combinations_seen.add(combination)
                    self.add_participant(
                        rs, new_id, course_map.get(rtrack['course_id']),
                        reg['persona_id'], is_instructor, is_orga)
            if not part['tracks']:
                # parts without courses
                self.add_participant(
                    rs, new_id, None, reg['persona_id'],
                    is_instructor=False, is_orga=is_orga)
        # Delete empty courses because they were cancelled
        for course_id in courses.keys():
            if course_id not in courses_seen:
                self.delete_past_course(rs, course_map[course_id])
            elif not courses[course_id]['active_segments']:
                self.logger.warning(
                    "Course {} remains without active parts.".format(
                        course_id))
        return new_id

    @access("cde_admin", "event_admin")
    def archive_event(self, rs: RequestState, event_id: int,
                      create_past_event: bool = True
                      ) -> Union[Tuple[None, str],
                                 Tuple[Optional[Tuple[int, ...]], None]]:
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :returns: The first entry are the ids of the new past events or None
          if there were complications or create_past_events is False.
          If there were complications, the second entry is an error message.
        """
        event_id = affirm("id", event_id)
        if ("cde_admin" not in rs.user.roles
                or "event_admin" not in rs.user.roles):
            raise PrivilegeError(n_("Needs both admin privileges."))
        with Atomizer(rs):
            event = self.event.get_event(rs, event_id)
            if any(now().date() < part['part_end']
                   for part in event['parts'].values()):
                return None, "Event not concluded."
            if event['offline_lock']:
                return None, "Event locked."
            self.event.set_event_archived(rs, {'id': event_id,
                                               'is_archived': True})
            new_ids = None
            if create_past_event:
                new_ids = tuple(self.archive_one_part(rs, event, part_id)
                                for part_id in xsorted(event['parts']))
        return new_ids, None
