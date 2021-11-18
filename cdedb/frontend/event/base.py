#!/usr/bin/env python3

"""
The `EventBaseFrontend` provides some basic frontend functionality for the event realm.

This implements the `AbstractUserFrontend` and overrides the `AbstractFrontend.render`
method to do some event specific preparation before rendering templates.

This offers both a global and a event-specific event log.

In addition the `EventBaseFrontend` provides a few helper methods that are used across
multiple of its subclasses.

The base aswell as all its subclasses (the event frontend mixins) combine together to
become the full `EventFrontend` in this modules `__init__.py`.
"""

import datetime
import operator
from collections import OrderedDict
from typing import Any, Collection, Dict, Optional, Tuple, Type

import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    EVENT_SCHEMA_VERSION, LOG_FIELDS_COMMON, CdEDBObject, CdEDBObjectMap, EntitySorter,
    KeyFunction, RequestState, Sortkey, get_localized_country_codes, merge_dicts, n_,
    unwrap, xsorted,
)
from cdedb.filter import enum_entries_filter
from cdedb.frontend.common import (
    AbstractUserFrontend, REQUESTdata, REQUESTdatadict, access, calculate_db_logparams,
    calculate_loglinks, event_guard, periodic,
)
from cdedb.query import QueryScope
from cdedb.validation import PERSONA_FULL_EVENT_CREATION, filter_none


class EventBaseFrontend(AbstractUserFrontend):
    """Provide the base for event frontend mixins."""
    realm = "event"

    def render(self, rs: RequestState, templatename: str,
               params: CdEDBObject = None) -> Response:
        params = params or {}
        if 'event' in rs.ambience:
            params['is_locked'] = self.is_locked(rs.ambience['event'])
            if rs.user.persona_id and "event" in rs.user.roles:
                reg_list = self.eventproxy.list_registrations(
                    rs, rs.ambience['event']['id'], rs.user.persona_id)
                params['is_registered'] = bool(reg_list)
                params['is_participant'] = False
                if params['is_registered']:
                    registration = self.eventproxy.get_registration(
                        rs, unwrap(reg_list.keys()))
                    if any(part['status']
                           == const.RegistrationPartStati.participant
                           for part in registration['parts'].values()):
                        params['is_participant'] = True
        return super().render(rs, templatename, params=params)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def is_locked(self, event: CdEDBObject) -> bool:
        """Shorthand to determine locking state of an event."""
        return event['offline_lock'] != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]

    @access("core_admin", "event_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return self.render(rs, "user/create_user")

    @access("core_admin", "event_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_EVENT_CREATION))
    def create_user(self, rs: RequestState, data: CdEDBObject) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("core_admin", "event_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices: Dict[str, OrderedDict[Any, str]] = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext)),
            'country': OrderedDict(get_localized_country_codes(rs)),
        }
        return self.generic_user_search(
            rs, download, is_search, QueryScope.event_user, QueryScope.event_user,
            self.eventproxy.submit_general_query, choices=choices,
            endpoint="user/user_search")

    @access("core_admin", "event_admin")
    @REQUESTdata("download", "is_search")
    def archived_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        events = self.pasteventproxy.list_past_events(rs)
        choices: Dict[str, Dict[Any, str]] = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        return self.generic_user_search(
            rs, download, is_search,
            QueryScope.archived_past_event_user, QueryScope.archived_persona,
            self.eventproxy.submit_general_query, choices=choices,
            endpoint="user/archived_user_search")

    @access("event")
    @REQUESTdata("part_id", "sortkey", "reverse")
    def participant_list(self, rs: RequestState, event_id: int,
                         part_id: vtypes.ID = None, sortkey: Optional[str] = "persona",
                         reverse: bool = False) -> Response:
        """List participants of an event"""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not (event_id in rs.user.orga or self.is_admin(rs)):
            assert rs.user.persona_id is not None
            if not self.eventproxy.check_registration_status(
                    rs, rs.user.persona_id, event_id,
                    {const.RegistrationPartStati.participant}):
                rs.notify('warning', n_("No participant of event."))
                return self.redirect(rs, "event/show_event")
            if not rs.ambience['event']['is_participant_list_visible']:
                rs.notify("error", n_("Participant list not published yet."))
                return self.redirect(rs, "event/show_event")
            reg_list = self.eventproxy.list_registrations(rs, event_id,
                                                          rs.user.persona_id)
            registration = self.eventproxy.get_registration(rs, unwrap(reg_list.keys()))
            list_consent = registration['list_consent']
        else:
            list_consent = True

        if part_id:
            part_ids = [part_id]
        else:
            part_ids = rs.ambience['event']['parts'].keys()

        data = self._get_participant_list_data(
            rs, event_id, part_ids, sortkey or "persona", reverse=reverse)
        if len(rs.ambience['event']['parts']) == 1:
            part_id = unwrap(rs.ambience['event']['parts'].keys())
        data['part_id'] = part_id
        data['list_consent'] = list_consent
        data['last_sortkey'] = sortkey
        data['last_reverse'] = reverse
        return self.render(rs, "base/participant_list", data)

    def _get_participant_list_data(
            self, rs: RequestState, event_id: int,
            part_ids: Collection[int] = (),
            sortkey: str = "persona", reverse: bool = False) -> CdEDBObject:
        """This provides data for download and online participant list.

        This is un-inlined so download_participant_list can use this
        as well."""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_participants(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)

        if not part_ids:
            part_ids = rs.ambience['event']['parts'].keys()
        if any(anid not in rs.ambience['event']['parts'] for anid in part_ids):
            raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
        parts = {anid: rs.ambience['event']['parts'][anid]
                 for anid in part_ids}

        participant = const.RegistrationPartStati.participant
        registrations = {
            k: v
            for k, v in registrations.items()
            if any(v['parts'][part_id]
                   and v['parts'][part_id]['status'] == participant
                   for part_id in parts)}
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id']
                      for e in registrations.values()), event_id)

        all_sortkeys = {
            "given_names": EntitySorter.given_names,
            "family_name": EntitySorter.family_name,
            "email": EntitySorter.email,
            "address": EntitySorter.address,
            "course": EntitySorter.course,
            "persona": EntitySorter.persona,
        }

        # FIXME: the result can have different lengths depending an amount of
        #  courses someone is assigned to.
        def sort_rank(sortkey: str, anid: int) -> Sortkey:
            prim_sorter: KeyFunction = all_sortkeys.get(
                sortkey, EntitySorter.persona)
            sec_sorter: KeyFunction = EntitySorter.persona
            if sortkey == "course":
                if not len(part_ids) == 1:
                    raise werkzeug.exceptions.BadRequest(n_(
                        "Only one part id allowed."))
                part_id = unwrap(part_ids)
                all_tracks = parts[part_id]['tracks']
                registered_tracks = [registrations[anid]['tracks'][track_id]
                                     for track_id in all_tracks]
                # TODO sort tracks by title?
                tracks = xsorted(
                    registered_tracks,
                    key=lambda track: all_tracks[track['track_id']]['sortkey'])
                course_ids = [track['course_id'] for track in tracks]
                prim_rank: Sortkey = tuple()
                for course_id in course_ids:
                    if course_id:
                        prim_rank += prim_sorter(courses[course_id])
                    else:
                        prim_rank += ("0", "", "")
            else:
                prim_key = personas[registrations[anid]['persona_id']]
                prim_rank = prim_sorter(prim_key)
            sec_key = personas[registrations[anid]['persona_id']]
            sec_rank = sec_sorter(sec_key)
            return prim_rank + sec_rank

        ordered = xsorted(registrations.keys(), reverse=reverse,
                          key=lambda anid: sort_rank(sortkey, anid))
        return {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'ordered': ordered, 'parts': parts,
        }

    @access("event")
    def participant_info(self, rs: RequestState, event_id: int) -> Response:
        """Display the `participant_info`, accessible only to participants."""
        if not (event_id in rs.user.orga or self.is_admin(rs)):
            assert rs.user.persona_id is not None
            if not self.eventproxy.check_registration_status(
                    rs, rs.user.persona_id, event_id,
                    {const.RegistrationPartStati.participant}):
                rs.notify('warning', n_("No participant of event."))
                return self.redirect(rs, "event/show_event")
        return self.render(rs, "base/participant_info")

    def _questionnaire_params(self, rs: RequestState, kind: const.QuestionnaireUsages
                              ) -> vtypes.TypeMapping:
        """Helper to construct a TypeMapping to extract questionnaire data."""
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, rs.ambience['event']['id'], kinds=(kind,)))

        def get_validator(row: CdEDBObject) -> Tuple[str, Type[Any]]:
            field = rs.ambience['event']['fields'][row['field_id']]
            type_ = vtypes.VALIDATOR_LOOKUP[field['kind'].name]
            if kind == const.QuestionnaireUsages.additional:
                type_ = Optional[type_]  # type: ignore[assignment]
            elif kind == const.QuestionnaireUsages.registration:
                if field['kind'] == const.FieldDatatypes.str:
                    type_ = Optional[type_]  # type: ignore[assignment]
            return (field['field_name'], type_)

        return dict(
            get_validator(entry) for entry in questionnaire
            if entry['field_id'] and not entry['readonly']
        )

    @staticmethod
    def calculate_groups(entity_ids: Collection[int], event: CdEDBObject,
                         registrations: CdEDBObjectMap, key: str,
                         personas: CdEDBObjectMap = None,
                         instructors: bool = True
                         ) -> Dict[Tuple[int, int], Collection[int]]:
        """Determine inhabitants/attendees of lodgements/courses.

        This has to take care only to select registrations which are
        actually present (and not cancelled or such).

        :param key: one of lodgement_id or course_id, signalling what to do
        :param personas: If provided this is used to sort the resulting
          lists by name, so that the can be displayed sorted.
        :param instructors: Include instructors of courses. No effect for
          lodgements.
        """
        tracks = event['tracks']
        if key == "course_id":
            aspect = 'tracks'
        elif key == "lodgement_id":
            aspect = 'parts'
        else:
            raise ValueError(n_(
                "Invalid key. Expected 'course_id' or 'lodgement_id"))

        def _check_belonging(entity_id: int, sub_id: int, reg_id: int) -> bool:
            """The actual check, un-inlined."""
            instance = registrations[reg_id][aspect][sub_id]
            if aspect == 'parts':
                part = instance
            elif aspect == 'tracks':
                part = registrations[reg_id]['parts'][tracks[sub_id]['part_id']]
            else:
                raise RuntimeError("impossible.")
            ret = (instance[key] == entity_id and
                    const.RegistrationPartStati(part['status']).is_present())
            if (ret and key == "course_id" and not instructors
                    and instance['course_instructor'] == entity_id):
                ret = False
            return ret

        if personas is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']])  # type: ignore
        if aspect == 'tracks':
            sub_ids = tracks.keys()
        elif aspect == 'parts':
            sub_ids = event['parts'].keys()
        else:
            raise RuntimeError("Impossible.")
        return {
            (entity_id, sub_id): xsorted(
                (registration_id for registration_id in registrations
                 if _check_belonging(entity_id, sub_id, registration_id)),
                key=sorter)
            for entity_id in entity_ids
            for sub_id in sub_ids
        }

    @access("event_admin", "auditor")
    @REQUESTdata(*LOG_FIELDS_COMMON, "event_id")
    def view_log(self, rs: RequestState, codes: Collection[const.EventLogCodes],
                 event_id: Optional[vtypes.ID], offset: Optional[int],
                 length: Optional[vtypes.PositiveInt],
                 persona_id: Optional[vtypes.CdedbID],
                 submitted_by: Optional[vtypes.CdedbID],
                 change_note: Optional[str],
                 time_start: Optional[datetime.datetime],
                 time_stop: Optional[datetime.datetime]) -> Response:
        """View activities concerning events organized via DB."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.eventproxy.retrieve_log(
            rs, codes, event_id, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        event_ids = {entry['event_id'] for entry in log if entry['event_id']}
        if self.is_admin(rs):
            registration_map = self.eventproxy.get_registration_map(rs, event_ids)
        else:
            registration_map = {}
        events = self.eventproxy.get_events(rs, event_ids)
        all_events = self.eventproxy.list_events(rs)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "base/view_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'events': events, 'all_events': all_events,
            'registration_map': registration_map, 'loglinks': loglinks})

    @access("event")
    @event_guard()
    @REQUESTdata(*LOG_FIELDS_COMMON)
    def view_event_log(self, rs: RequestState,
                       codes: Collection[const.EventLogCodes],
                       event_id: int, offset: Optional[int],
                       length: Optional[vtypes.PositiveInt],
                       persona_id: Optional[vtypes.CdedbID],
                       submitted_by: Optional[vtypes.CdedbID],
                       change_note: Optional[str],
                       time_start: Optional[datetime.datetime],
                       time_stop: Optional[datetime.datetime]) -> Response:
        """View activities concerning one event organized via DB."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.eventproxy.retrieve_log(
            rs, codes, event_id, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        registration_map = self.eventproxy.get_registration_map(rs, (event_id,))
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "base/view_event_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'registration_map': registration_map, 'loglinks': loglinks})

    @periodic("event_keeper", 4)
    def event_keeper(self, rs: RequestState, state: CdEDBObject) -> CdEDBObject:
        """Regularly backup any event that got changed."""
        if not state:
            state = {
                'EVENT_SCHEMA_VERSION': None,
                'events': {}
            }
        event_ids = self.eventproxy.list_events(rs, archived=False)
        if state.get("EVENT_SCHEMA_VERSION") != list(EVENT_SCHEMA_VERSION):
            self.logger.info("Event schema version changed, creating new commit for"
                             " every event.")
            for event_id in event_ids:
                self.eventproxy.event_keeper_commit(
                    rs, event_id, "Schema-Version hat sich geändert.")
            state['EVENT_SCHEMA_VERSION'] = EVENT_SCHEMA_VERSION

        commit_msg = "Regelmäßiges Backup."
        for event_id in event_ids:
            if event_id not in state['events']:
                state['events'][event_id] = 0
            _, entries = self.eventproxy.retrieve_log(rs, event_id=event_id, length=1)
            if entries:
                # this can only happen for missing logs (e.g. test data)
                log_entry_id = unwrap(entries)['id']
            else:
                log_entry_id = 0
            if not log_entry_id or log_entry_id > state['events'][event_id]:
                self.eventproxy.event_keeper_commit(rs, event_id, commit_msg)
                state['events'][event_id] = log_entry_id

        return state
