#!/usr/bin/env python3

"""Past event related services for the cde realm.

Viewing and searching past events and courses requires the "member" role,
administrative tasks, like creating and modifying past events and courses requires
"cde_admin".
"""

import copy
import csv
from collections import OrderedDict
from collections.abc import Sequence
from typing import Optional

from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, CdEDBObjectMap, RequestState, merge_dicts
from cdedb.common.n_ import n_
from cdedb.common.query import QueryOperators, QueryScope
from cdedb.common.query.log_filter import PastEventLogFilter
from cdedb.common.sorting import EntitySorter, xsorted
from cdedb.common.validation.validate import (
    PAST_COURSE_COMMON_FIELDS,
    PAST_EVENT_FIELDS,
)
from cdedb.frontend.cde.base import CdEBaseFrontend
from cdedb.frontend.common import (
    CustomCSVDialect,
    REQUESTdata,
    REQUESTdatadict,
    TransactionObserver,
    access,
    check_validation as check,
)

COURSESEARCH_DEFAULTS = {
    'qsel_courses.title': True,
    'qop_courses.title': QueryOperators.match,
    'qsel_events.title': True,
    'qop_events.title': QueryOperators.match,
    'qop_courses.nr': QueryOperators.match,
    'qop_courses.description': QueryOperators.match,
    'qsel_courses.pevent_id': True,
    'qsel_events.tempus': True,
    'qord_0': 'courses.title',
    'qord_0_ascending': True,
    'qord_1': 'events.tempus',
    'qord_1_ascending': False,
}


class CdEPastEventMixin(CdEBaseFrontend):
    @access("member", "cde_admin")
    @REQUESTdata("is_search")
    def past_course_search(self, rs: RequestState, is_search: bool) -> Response:
        """Search for past courses."""
        defaults = copy.deepcopy(COURSESEARCH_DEFAULTS)
        scope = QueryScope.past_event_course
        spec = scope.get_spec()
        query = check(rs, vtypes.QueryInput,
                      scope.mangle_query_input(rs, defaults), "query", spec=spec,
                      allow_empty=not is_search, separator=" ")
        result: Optional[Sequence[CdEDBObject]] = None
        count = 0

        if rs.has_validation_errors():
            self._fix_search_validation_error_references(rs)
        else:
            assert query is not None
            if is_search and not query.constraints:
                rs.notify("error", n_("You have to specify some filters."))
            elif is_search:
                query.fields_of_interest.append('courses.id')
                result = self.pasteventproxy.submit_general_query(rs, query)
                count = len(result)
                if count == 1:
                    return self.redirect(rs, "cde/show_past_course", {
                        'pevent_id': result[0]['courses.pevent_id'],
                        'pcourse_id': result[0]['courses.id']})

        return self.render(rs, "past_event/past_course_search", {
            'spec': spec, 'result': result, 'count': count})

    def _process_participants(self, rs: RequestState, pevent_id: int,
                              pcourse_id: Optional[int] = None,
                              orgas_only: bool = False,
                              ) -> tuple[CdEDBObjectMap, CdEDBObjectMap, int]:
        """Helper to pretty up participation infos.

        The problem is, that multiple participations can be logged for a
        persona per event (easiest example multiple courses in multiple
        parts). So here we fuse these entries into one per persona.

        Additionally, this function takes care of privacy: Participants
        are removed from the result if they are not searchable and the viewing
        user is neither admin nor participant of the past event themselves.

        Note that the returned dict of participants is already sorted.

        :param pcourse_id: if not None, restrict to participants of this
          course
        :returns: This returns three things: the processed participants,
          the persona data sets of the participants and the number of
          redacted participants.
        """
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        # We are privileged to see other participants if we are admin (and have
        # the relevant admin view enabled) or participant by ourselves
        privileged = is_participant or "past_event" in rs.user.admin_views
        proto_participants = {}
        participants = {}
        personas: CdEDBObjectMap = {}
        extra_participants = 0

        persona_ids = {persona_id
                       for persona_id, _ in participant_infos.keys()}
        for persona_id in persona_ids:
            base_set = tuple(x for x in participant_infos.values()
                             if x['persona_id'] == persona_id)
            entry: CdEDBObject = {
                'pevent_id': pevent_id,
                'persona_id': persona_id,
                'is_orga': any(x['is_orga'] for x in base_set),
                'pcourse_ids': tuple(x['pcourse_id'] for x in base_set),
                'instructor': set(
                        x['pcourse_id'] for x in base_set if (
                            x['is_instructor'] and (x['pcourse_id'] == pcourse_id
                                                    or not pcourse_id))),
            }
            if pcourse_id and pcourse_id not in entry['pcourse_ids']:
                # remove non-participants with respect to the relevant
                # course if there is a relevant course
                continue
            if orgas_only and not entry['is_orga']:
                # remove non-orgas
                continue
            proto_participants[persona_id] = entry

        if privileged or ("searchable" in rs.user.roles):
            # Commit to releasing the information
            participants = proto_participants
            personas = self.coreproxy.get_personas(rs, participants.keys())
            participants = OrderedDict(xsorted(
                participants.items(),
                key=lambda x: EntitySorter.persona(personas[x[0]])))

            # Delete unsearchable participants if we are not privileged
            if not privileged:
                for anid, persona in personas.items():
                    if not persona['is_searchable'] or not persona['is_member']:
                        del participants[anid]
                        extra_participants += 1
        else:
            extra_participants = len(proto_participants)
        # Flag linkable user profiles (own profile + all searchable profiles
        # + all (if we are admin))
        for anid in participants:
            participants[anid]['viewable'] = (self.is_admin(rs)
                                              or anid == rs.user.persona_id)
        if "searchable" in rs.user.roles:
            for anid in participants:
                if (personas[anid]['is_searchable']
                        and personas[anid]['is_member']):
                    participants[anid]['viewable'] = True
        return participants, personas, extra_participants

    @access("member", "cde_admin")
    def show_past_event(self, rs: RequestState, pevent_id: int) -> Response:
        """Display concluded event."""
        course_ids = self.pasteventproxy.list_past_courses(rs, pevent_id)
        courses = self.pasteventproxy.get_past_courses(rs, course_ids)
        participants, personas, extra_participants = self._process_participants(
            rs, pevent_id)
        orgas, _, extra_orgas = self._process_participants(rs, pevent_id,
                                                           orgas_only=True)
        for p_id, p in participants.items():
            p['pcourses'] = {
                pc_id: {
                    k: courses[pc_id][k]
                    for k in ('id', 'title', 'nr')
                }
                for pc_id in p['pcourse_ids']
                if pc_id
            }
        participant_infos = self.pasteventproxy.list_participants(
            rs, pevent_id=pevent_id)
        is_participant = any(anid == rs.user.persona_id
                             for anid, _ in participant_infos.keys())
        return self.render(rs, "past_event/show_past_event", {
            'courses': courses, 'personas': personas, 'participants': participants,
            'extra_participants': extra_participants, 'orgas': orgas,
            'extra_orgas': extra_orgas, 'is_participant': is_participant,
        })

    @access("member", "cde_admin")
    def show_past_course(self, rs: RequestState, pevent_id: int,
                         pcourse_id: int) -> Response:
        """Display concluded course."""
        participants, personas, extra_participants = self._process_participants(
            rs, pevent_id, pcourse_id=pcourse_id)
        return self.render(rs, "past_event/show_past_course", {
            'participants': participants, 'personas': personas,
            'extra_participants': extra_participants})

    @access("member", "cde_admin")
    @REQUESTdata("institution")
    def list_past_events(self, rs: RequestState,
                         institution: Optional[const.PastInstitutions] = None,
                         ) -> Response:
        """List all concluded events."""
        if rs.has_validation_errors():
            rs.notify('warning', n_("Institution parameter got lost."))
        events = self.pasteventproxy.list_past_events(rs)
        shortnames = {
            pevent_id: value['shortname']
            for pevent_id, value in
            self.pasteventproxy.get_past_events(rs, events).items()
        }
        stats = self.pasteventproxy.past_event_stats(rs)

        # Generate (reverse) chronologically sorted list of past event ids
        stats_sorter = xsorted(stats, key=lambda x: events[x])
        stats_sorter.sort(key=lambda x: stats[x]['tempus'], reverse=True)
        # Bunch past events by years
        # Using idea from http://stackoverflow.com/a/8983196
        years: dict[int, list[int]] = {}
        for anid in stats_sorter:
            if institution and stats[anid]['institution'] != institution:
                continue
            years.setdefault(stats[anid]['tempus'].year, []).append(anid)

        return self.render(rs, "past_event/list_past_events", {
            'events': events,
            'stats': stats,
            'years': years,
            'shortnames': shortnames,
        })

    @access("cde_admin")
    def change_past_event_form(self, rs: RequestState, pevent_id: int,
                               ) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['pevent'])
        return self.render(rs, "past_event/change_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_EVENT_FIELDS)
    def change_past_event(self, rs: RequestState, pevent_id: int,
                          data: CdEDBObject) -> Response:
        """Modify a concluded event."""
        data['id'] = pevent_id
        data = check(rs, vtypes.PastEvent, data)
        if rs.has_validation_errors():
            return self.change_past_event_form(rs, pevent_id)
        assert data is not None
        code = self.pasteventproxy.set_past_event(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin")
    def create_past_event_form(self, rs: RequestState) -> Response:
        """Render form."""
        return self.render(rs, "past_event/create_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_EVENT_FIELDS)
    @REQUESTdata("courses")
    def create_past_event(self, rs: RequestState, courses: Optional[str],
                          data: CdEDBObject) -> Response:
        """Add new concluded event."""
        data = check(rs, vtypes.PastEvent, data, creation=True)
        thecourses: list[CdEDBObject] = []
        if courses:
            courselines = courses.split('\n')
            reader = csv.DictReader(
                courselines, fieldnames=("nr", "title", "description"),
                dialect=CustomCSVDialect())
            lineno = 0
            pcourse: Optional[CdEDBObject]
            for pcourse in reader:
                lineno += 1
                # This is a placeholder for validation and will be substituted
                # later. The typechecker expects a str here.
                assert pcourse is not None
                pcourse['pevent_id'] = "1"
                pcourse = check(rs, vtypes.PastCourse, pcourse, creation=True)
                if pcourse:
                    thecourses.append(pcourse)
                else:
                    rs.notify("warning", n_("Line %(lineno)s is faulty."),
                              {'lineno': lineno})
        if rs.has_validation_errors():
            return self.create_past_event_form(rs)
        assert data is not None
        with TransactionObserver(rs, self, "create_past_event"):
            new_id = self.pasteventproxy.create_past_event(rs, data)
            for course in thecourses:
                course['pevent_id'] = new_id
                self.pasteventproxy.create_past_course(rs, course)
        rs.notify_return_code(new_id, success=n_("Event created."))
        return self.redirect(rs, "cde/show_past_event", {'pevent_id': new_id})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def delete_past_event(self, rs: RequestState, pevent_id: int,
                          ack_delete: bool) -> Response:
        """Remove a past event."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_past_event(rs, pevent_id)

        code = self.pasteventproxy.delete_past_event(
            rs, pevent_id, cascade=("courses", "participants", "log", "genesis_cases"))
        rs.notify_return_code(code)
        return self.redirect(rs, "cde/list_past_events")

    @access("cde_admin")
    def change_past_course_form(self, rs: RequestState, pevent_id: int,
                                pcourse_id: int) -> Response:
        """Render form."""
        merge_dicts(rs.values, rs.ambience['pcourse'])
        return self.render(rs, "past_event/change_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_COURSE_COMMON_FIELDS)
    def change_past_course(self, rs: RequestState, pevent_id: int,
                           pcourse_id: int, data: CdEDBObject) -> Response:
        """Modify a concluded course."""
        data['id'] = pcourse_id
        data = check(rs, vtypes.PastCourse, data)
        if rs.has_validation_errors():
            return self.change_past_course_form(rs, pevent_id, pcourse_id)
        assert data is not None
        code = self.pasteventproxy.set_past_course(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "cde/show_past_course")

    @access("cde_admin")
    def create_past_course_form(self, rs: RequestState, pevent_id: int,
                                ) -> Response:
        """Render form."""
        return self.render(rs, "past_event/create_past_course")

    @access("cde_admin", modi={"POST"})
    @REQUESTdatadict(*PAST_COURSE_COMMON_FIELDS)
    def create_past_course(self, rs: RequestState, pevent_id: int,
                           data: CdEDBObject) -> Response:
        """Add new concluded course."""
        data['pevent_id'] = pevent_id
        data = check(rs, vtypes.PastCourse, data, creation=True)
        if rs.has_validation_errors():
            return self.create_past_course_form(rs, pevent_id)
        assert data is not None
        new_id = self.pasteventproxy.create_past_course(rs, data)
        rs.notify_return_code(new_id, success=n_("Course created."))
        return self.redirect(rs, "cde/show_past_course", {'pcourse_id': new_id})

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("ack_delete")
    def delete_past_course(self, rs: RequestState, pevent_id: int,
                           pcourse_id: int, ack_delete: bool) -> Response:
        """Delete a concluded course.

        This also deletes all participation information w.r.t. this course.
        """
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_past_course(rs, pevent_id, pcourse_id)

        code = self.pasteventproxy.delete_past_course(
            rs, pcourse_id, cascade=("participants", "genesis_cases"))
        rs.notify_return_code(code)
        return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("pcourse_id", "persona_ids", "is_instructor", "is_orga")
    def add_participants(self, rs: RequestState, pevent_id: int,
                         pcourse_id: Optional[vtypes.ID],
                         persona_ids: vtypes.CdedbIDList,
                         is_instructor: bool, is_orga: bool) -> Response:
        """Add participant to concluded event."""
        if rs.has_validation_errors():
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)

        # Check presence of valid event users for the given ids
        if not self.coreproxy.verify_ids(rs, persona_ids, is_archived=None):
            rs.append_validation_error(
                ("persona_ids",
                 ValueError(n_("Some of these users do not exist."))))
        if not self.coreproxy.verify_personas(rs, persona_ids, {"event"}):
            rs.append_validation_error(
                ("persona_ids",
                 ValueError(n_("Some of these users are not event users."))))
        if rs.has_validation_errors():
            if pcourse_id:
                return self.show_past_course(rs, pevent_id, pcourse_id)
            else:
                return self.show_past_event(rs, pevent_id)

        code = 1
        # TODO: Check if participants are already present.
        for persona_id in persona_ids:
            code *= self.pasteventproxy.add_participant(
                rs, pevent_id, pcourse_id, persona_id, is_instructor, is_orga)
        rs.notify_return_code(code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course",
                                 {'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @access("cde_admin", modi={"POST"})
    @REQUESTdata("persona_id", "pcourse_id")
    def remove_participant(self, rs: RequestState, pevent_id: int,
                           persona_id: vtypes.ID, pcourse_id: Optional[vtypes.ID],
                           ) -> Response:
        """Remove participant."""
        if rs.has_validation_errors():
            return self.show_past_event(rs, pevent_id)
        code = self.pasteventproxy.remove_participant(
            rs, pevent_id, pcourse_id, persona_id)
        rs.notify_return_code(code)
        if pcourse_id:
            return self.redirect(rs, "cde/show_past_course", {
                'pcourse_id': pcourse_id})
        else:
            return self.redirect(rs, "cde/show_past_event")

    @REQUESTdatadict(*PastEventLogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("cde_admin", "auditor")
    def view_past_log(self, rs: RequestState, data: CdEDBObject, download: bool,
                      ) -> Response:
        """View activities concerning concluded events."""
        pevent_ids = self.pasteventproxy.list_past_events(rs)
        pevents = self.pasteventproxy.get_past_events(rs, pevent_ids)
        return self.generic_view_log(
            rs, data, PastEventLogFilter, self.pasteventproxy.retrieve_past_log,
            download=download, template="past_event/view_past_log", template_kwargs={
                'pevents': pevents,
            },
        )
