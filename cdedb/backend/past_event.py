#!/usr/bin/env python3

"""The past event backend provides means to catalogue information about
concluded events.
"""

import datetime

from cdedb.backend.common import (
    access, affirm_validation as affirm, Silencer, AbstractBackend,
    affirm_set_validation as affirm_set, singularize)
from cdedb.backend.event import EventBackend
from cdedb.common import (
    n_, glue, PAST_EVENT_FIELDS, PAST_COURSE_FIELDS, PrivilegeError,
    unwrap, now, ProxyShim, INSTITUTION_FIELDS)
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const


class PastEventBackend(AbstractBackend):
    """Handle concluded events.

    This is somewhere between CdE and event realm, so we split it into
    its own realm.
    """
    realm = "past_event"

    def __init__(self, configpath):
        super().__init__(configpath)
        self.event = ProxyShim(EventBackend(configpath), internal=True)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("cde", "event")
    @singularize("participation_info")
    def participation_infos(self, rs, ids):
        """List concluded events visited by specific personas.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: [dict]}
        :returns: Keys are the ids and items are the event lists.
        """
        ids = affirm_set("id", ids)
        query = glue(
            "SELECT p.persona_id, p.pevent_id, e.title AS event_name,",
            "e.tempus, p.pcourse_id, c.title AS course_name, c.nr,",
            "p.is_instructor, p.is_orga",
            "FROM past_event.participants AS p",
            "INNER JOIN past_event.events AS e ON (p.pevent_id = e.id)",
            "LEFT OUTER JOIN past_event.courses AS c ON (p.pcourse_id = c.id)",
            "WHERE p.persona_id = ANY(%s)")
        pevents = self.query_all(rs, query, (ids,))
        ret = {}
        for anid in ids:
            ret[anid] = tuple(x for x in pevents if x['persona_id'] == anid)
        return ret

    def past_event_log(self, rs, code, pevent_id, persona_id=None,
                       additional_info=None):
        """Make an entry in the log for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of
          :py:class:`cdedb.database.constants.PastEventLogCodes`.
        :type pevent_id: int or None
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
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
    def retrieve_past_log(self, rs, codes=None, pevent_id=None, start=None,
                          stop=None, persona_id=None, submitted_by=None,
                          additional_info=None, time_start=None,
                          time_stop=None):
        """Get recorded activity for concluded events.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type pevent_id: int or None
        :type start: int or None
        :type stop: int or None
        :type persona_id: int or None
        :type submitted_by: int or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :rtype: [{str: object}]
        """
        return self.generic_retrieve_log(
            rs, "enum_pasteventlogcodes", "pevent", "past_event.log", codes,
            entity_id=pevent_id, start=start, stop=stop, persona_id=persona_id,
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)

    @access("cde", "event")
    def list_institutions(self, rs):
        """List all institutions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: str}
        :returns: Mapping of institution ids to titles.
        """
        query = "SELECT id, title FROM past_event.institutions"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde", "event")
    @singularize("get_institution")
    def get_institutions(self, rs, ids):
        """Retrieve data for some institutions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.institutions",
                               INSTITUTION_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("cde_admin", "event_admin")
    def set_institution(self, rs, data):
        """Update some keys of an institution.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("institution", data)
        ret = self.sql_update(rs, "past_event.institutions", data)
        current = unwrap(self.get_institutions(rs, (data['id'],)))
        self.past_event_log(rs, const.PastEventLogCodes.institution_changed,
                            pevent_id=None, additional_info=current['title'])
        return ret

    @access("cde_admin", "event_admin")
    def create_institution(self, rs, data):
        """Make a new institution.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new institution
        """
        data = affirm("institution", data, creation=True)
        ret = self.sql_insert(rs, "past_event.institutions", data)
        self.past_event_log(rs, const.PastEventLogCodes.institution_created,
                            pevent_id=None, additional_info=data['title'])
        return ret

    @access("cde_admin", "event_admin")
    def delete_institution(self, rs, institution_id, cascade=False):
        """Remove an institution

        The institution may not be referenced.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type institution_id: int
        :type cascade: bool
        :param cascade: Must be False.
        :rtype: int
        :returns: default return code
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
    def list_past_events(self, rs):
        """List all concluded events.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM past_event.events"
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['title'] for e in data}

    @access("cde")
    def past_event_stats(self, rs):
        """Additional information about concluded events.

        This is mostly an extended version of the listing function which
        provides aggregate data without the need to shuttle the complete
        table to the frontend.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {int: {str: int}}
        :returns: Mapping of event ids to stats.
        """
        query = glue(
            "SELECT events.id AS pevent_id, tempus,",
            "institutions.id AS institution_id, institutions.moniker",
            "FROM past_event.events LEFT JOIN past_event.institutions",
            "ON institutions.id = events.institution")
        data = self.query_all(rs, query, tuple())
        ret = {e['pevent_id']: {'tempus': e['tempus'],
                                'institution_id': e['institution_id'],
                                'institution_moniker': e['moniker'],
                                'courses': 0,
                                'participants': 0
                                }
               for e in data}
        query = glue(
            "SELECT events.id, COUNT(*) AS courses FROM past_event.events",
            "JOIN past_event.courses ON courses.pevent_id = events.id",
            "GROUP BY events.id")
        data = self.query_all(rs, query, tuple())
        for e in data:
            ret[e['id']]['courses'] = e['courses']
        query = glue(
            "SELECT subquery.id, COUNT(*) AS participants FROM",
            "(SELECT DISTINCT events.id, participants.persona_id",
            "FROM past_event.events JOIN past_event.participants",
            "ON participants.pevent_id = events.id) AS subquery",
            "GROUP BY subquery.id")
        data = self.query_all(rs, query, tuple())
        for e in data:
            ret[e['id']]['participants'] = e['participants']
        return ret

    @access("cde", "event")
    @singularize("get_past_event")
    def get_past_events(self, rs, ids):
        """Retrieve data for some concluded events.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.events", PAST_EVENT_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("cde_admin", "event_admin")
    def set_past_event(self, rs, data):
        """Update some keys of a concluded event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("past_event", data)
        ret = self.sql_update(rs, "past_event.events", data)
        self.past_event_log(rs, const.PastEventLogCodes.event_changed,
                            data['id'])
        return ret

    @access("cde_admin", "event_admin")
    def create_past_event(self, rs, data):
        """Make a new concluded event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("past_event", data, creation=True)
        ret = self.sql_insert(rs, "past_event.events", data)
        self.past_event_log(rs, const.PastEventLogCodes.event_created, ret)
        return ret

    @access("cde_admin")
    def delete_past_event_blockers(self, rs, pevent_id):
        """Determine what keeps a past event from being deleted.

        Possible blockers:

        * participants: A participant of the past event or one of its
                        courses.
        * courses: A course associated with the past event.
        * log: A log entry for the past event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int
        :rtype: {str: [int]}
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
    def delete_past_event(self, rs, pevent_id, cascade=None):
        """Remove past event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
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
    def list_past_courses(self, rs, pevent_id):
        """List all courses of a concluded event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int
        :rtype: {int: str}
        :returns: Mapping of course ids to titles.
        """
        pevent_id = affirm("id", pevent_id)
        data = self.sql_select(rs, "past_event.courses", ("id", "title"),
                               (pevent_id,), entity_key="pevent_id")
        return {e['id']: e['title'] for e in data}

    @access("cde", "event")
    @singularize("get_past_course")
    def get_past_courses(self, rs, ids):
        """Retrieve data for some concluded courses.

        They do not need to be associated to the same event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "past_event.courses", PAST_COURSE_FIELDS,
                               ids)
        return {e['id']: e for e in data}

    @access("cde_admin", "event_admin")
    def set_past_course(self, rs, data):
        """Update some keys of a concluded course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("past_course", data)
        ret = self.sql_update(rs, "past_event.courses", data)
        current = self.sql_select_one(rs, "past_event.courses",
                                      ("title", "pevent_id"), data['id'])
        self.past_event_log(
            rs, const.PastEventLogCodes.course_changed, current['pevent_id'],
            additional_info=current['title'])
        return ret

    @access("cde_admin", "event_admin")
    def create_past_course(self, rs, data):
        """Make a new concluded course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new course
        """
        data = affirm("past_course", data, creation=True)
        ret = self.sql_insert(rs, "past_event.courses", data)
        self.past_event_log(rs, const.PastEventLogCodes.course_created,
                            data['pevent_id'], additional_info=data['title'])
        return ret

    @access("cde_admin")
    def delete_past_course_blockers(self, rs, pcourse_id):
        """Determine what keeps a past course from being deleted.

        Possible blockers:

        * participants: Participants of the past course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pcourse_id: int
        :rtype: {str: [int]}
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
    def delete_past_course(self, rs, pcourse_id, cascade=None):
        """Remove past course.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pcourse_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
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
    def add_participant(self, rs, pevent_id, pcourse_id, persona_id,
                        is_instructor, is_orga):
        """Add a participant to a concluded event.

        A persona can participate multiple times in a single event. For
        example if she took several courses in different parts of the event.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int
        :type pcourse_id: int or None
        :param pcourse_id: If None the persona participated in the event, but
          not in a course (this should be common for orgas).
        :type persona_id: int
        :type is_instructor: bool
        :type is_orga: bool
        :rtype: int
        :returns: default return code
        """
        data = {}
        data['persona_id'] = affirm("id", persona_id)
        data['pevent_id'] = affirm("id", pevent_id)
        data['pcourse_id'] = affirm("id_or_None", pcourse_id)
        data['is_instructor'] = affirm("bool", is_instructor)
        data['is_orga'] = affirm("bool", is_orga)
        ret = self.sql_insert(rs, "past_event.participants", data)
        self.past_event_log(
            rs, const.PastEventLogCodes.participant_added, pevent_id,
            persona_id=persona_id)
        return ret

    @access("cde_admin", "event_admin")
    def remove_participant(self, rs, pevent_id, pcourse_id, persona_id):
        """Remove a participant from a concluded event.

        All attributes have to match exactly, so that if someone
        participated multiple times (for example in different courses) we
        are able to delete an exact instance.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int
        :type pcourse_id: int or None
        :type persona_id: int
        :rtype: int
        :returns: default return code
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
    def list_participants(self, rs, *, pevent_id=None, pcourse_id=None):
        """List all participants of a concluded event or course.

        Exactly one of the inputs has to be provided.

        .. note:: The return value uses two integers as key, since only the
          persona id is not unique.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type pevent_id: int or None
        :type pcourse_id: int or None
        :rtype: {(int, int): {str: object}}
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
    def find_past_event(self, rs, moniker):
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
        warnings = []
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
    def find_past_course(self, rs, phrase, pevent_id):
        """Look for courses with a certain number/name.

        This is mainly for batch admission, where we want to
        automatically resolve past courses to their ids.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type phrase: str
        :type pevent_id: int
        :param pevent_id: Restrict to courses of this past event.
        :rtype: (int or None, [exception])
        :returns: The id of the past course or None if there were errors.
        """
        phrase = affirm("str_or_None", phrase)
        if not phrase:
            return None, [], [("pcourse_id",
                               ValueError(n_("No input supplied.")))]
        pevent_id = affirm("id", pevent_id)
        query = glue("SELECT id FROM past_event.courses",
                     "WHERE nr = %s AND pevent_id = %s")
        query2 = glue("SELECT id FROM past_event.courses",
                     "WHERE title ~* %s AND pevent_id = %s")
        query3 = glue("SELECT id FROM past_event.courses",
                      "WHERE similarity(title, %s) > %s AND pevent_id = %s")
        ret = self.query_all(rs, query, (phrase, pevent_id))
        warnings = []
        # retry with less restrictive conditions until we find something or
        # give up
        if len(ret) == 0:
            warnings.append(("pcourse_id", ValueError(n_("Only title match."))))
            ret = self.query_all(rs, query2, (phrase, pevent_id))
        if len(ret) == 0:
            warnings.append(("pcourse_id", ValueError(n_("Only fuzzy match."))))
            ret = self.query_all(rs, query3, (phrase, 0.5, pevent_id))
        if len(ret) == 0:
            return None, [], [
                ("pcourse_id", ValueError(n_("No course found.")))]
        elif len(ret) > 1:
            return None, warnings, [("pcourse_id",
                                     ValueError(n_("Ambiguous course.")))]
        else:
            return unwrap(unwrap(ret)), warnings, []

    def archive_one_part(self, rs, event, part_id):
        """Uninlined code from :py:meth:`archive_event`

        This assumes implicit atomization by the caller.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event: {str: object}
        :type part_id: int
        :rtype: int
        :returns: ID of the newly created past event.
        """
        part = event['parts'][part_id]
        pevent = {k: v for k, v in event.items()
                  if k in PAST_EVENT_FIELDS}
        pevent['tempus'] = part['part_begin']
        if len(event['parts']) > 1:
            # Add part designation in case of events with multiple parts
            pevent['title'] += " ({})".format(part['title'])
            pevent['shortname'] += " ({})".format(part['shortname'])
        del pevent['id']
        new_id = self.create_past_event(rs, pevent)
        course_ids = self.event.list_db_courses(rs, event['id'])
        courses = self.event.get_courses(rs, course_ids.keys())
        course_map = {}
        for course_id, course in courses.items():
            pcourse = {k: v for k, v in course.items()
                       if k in PAST_COURSE_FIELDS}
            del pcourse['id']
            pcourse['pevent_id'] = new_id
            pcourse_id = self.create_past_course(rs, pcourse)
            course_map[course_id] = pcourse_id
        reg_ids = self.event.list_registrations(rs, event['id'])
        regs = self.event.get_registrations(rs, reg_ids.keys())
        # we want to later delete empty courses
        courses_seen = set()
        # we want to add each participant/course combination at
        # most once
        combinations_seen = set()
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
    def archive_event(self, rs, event_id):
        """Transfer data from a concluded event into the past event schema.

        The data of the event organization is scheduled to be deleted at
        some point. We retain in the past_event schema only the
        participation information. This automates the process of converting
        data from one schema to the other.

        We export each event part into a separate past event since
        semantically the event parts mostly behave like separate events
        which happen to take place consecutively.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type event_id: int
        :rtype: ([int] or None, str or None)
        :returns: The first entry are the ids of the new past events or None
          if there were complications. In the latter case the second entry
          is an error message.
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
            new_ids = tuple(self.archive_one_part(rs, event, part_id)
                            for part_id in sorted(event['parts']))
        return new_ids, None
