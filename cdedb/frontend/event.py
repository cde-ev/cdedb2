#!/usr/bin/env python3

"""Services for the event realm."""

import collections.abc
import copy
import csv
import datetime
import decimal
import functools
import itertools
import json
import operator
import pathlib
import re
import shutil
import tempfile
from collections import Counter, OrderedDict
from typing import (
    Any, Callable, Collection, Dict, List, Mapping, NamedTuple, Optional, Set,
    Tuple, Union, cast,
)

import psycopg2.extensions
import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
import cdedb.validationtypes as vtypes
from cdedb.common import (
    DEFAULT_NUM_COURSE_CHOICES, EVENT_FIELD_SPEC, LOG_FIELDS_COMMON, AgeClasses,
    CdEDBObject, CdEDBObjectMap, CdEDBOptionalMap, CourseChoiceToolActions,
    CourseFilterPositions, DefaultReturnCode, EntitySorter, Error, InfiniteEnum,
    KeyFunction, LodgementsSortkeys, PartialImportError, RequestState, Sortkey,
    asciificator, deduct_years, determine_age_class, diacritic_patterns, get_hash, glue,
    json_serialize, merge_dicts, mixed_existence_sorter, n_, now, unwrap, xsorted,
)
from cdedb.database.connection import Atomizer
from cdedb.frontend.common import (
    AbstractUserFrontend, CustomCSVDialect, RequestConstraint, REQUESTdata,
    REQUESTdatadict, REQUESTfile, access, calculate_db_logparams, calculate_loglinks,
    cdedbid_filter, cdedburl, check_validation as check,
    check_validation_optional as check_optional, enum_entries_filter, event_guard,
    keydictsort_filter, make_event_fee_reference, process_dynamic_input,
    querytoparams_filter, request_extractor, safe_filter,
)
from cdedb.query import (
    QUERY_SPECS, Query, QueryConstraint, QueryOperators, mangle_query_input,
)
from cdedb.validation import (
    COURSE_COMMON_FIELDS, EVENT_EXPOSED_FIELDS, LODGEMENT_COMMON_FIELDS,
    PERSONA_FULL_EVENT_CREATION, TypeMapping, filter_none, validate_check,
    EVENT_PART_COMMON_FIELDS
)
from cdedb.validationtypes import VALIDATOR_LOOKUP

LodgementProblem = NamedTuple(
    "LodgementProblem", [("description", str), ("lodgement_id", int),
                         ("part_id", int), ("reg_ids", Collection[int]),
                         ("severeness", int)])
EntitySetter = Callable[[RequestState, Dict[str, Any]], int]


class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
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

    @staticmethod
    def event_has_field(event: CdEDBObject, field_name: str,
                        association: const.FieldAssociations) -> bool:
        """Shorthand to check whether a field with given name and
        association is defined for an event.
        """
        return any((field['field_name'] == field_name
                    and field['association'] == field_name)
                   for field in event['fields'].values())

    @staticmethod
    def event_has_tracks(event: CdEDBObject) -> bool:
        """Shorthand to check whether an event has course tracks."""
        return any(part['tracks'] for part in event['parts'].values())

    @access("anonymous")
    def index(self, rs: RequestState) -> Response:
        """Render start page."""
        open_event_list = self.eventproxy.list_events(
            rs, visible=True, current=True, archived=False)
        other_event_list = self.eventproxy.list_events(
            rs, visible=True, current=False, archived=False)
        open_events = self.eventproxy.get_events(rs, open_event_list)
        other_events = self.eventproxy.get_events(
            rs, set(other_event_list) - set(rs.user.orga))
        orga_events = self.eventproxy.get_events(rs, rs.user.orga)

        if "event" in rs.user.roles:
            for event_id, event in open_events.items():
                registration = self.eventproxy.list_registrations(
                    rs, event_id, rs.user.persona_id)
                event['registration'] = bool(registration)

        return self.render(rs, "index", {
            'open_events': open_events, 'orga_events': orga_events,
            'other_events': other_events})

    @access("core_admin", "event_admin")
    def create_user_form(self, rs: RequestState) -> Response:
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("core_admin", "event_admin", modi={"POST"})
    @REQUESTdatadict(*filter_none(PERSONA_FULL_EVENT_CREATION))
    def create_user(self, rs: RequestState, data: CdEDBObject,
                    ignore_warnings: bool = False) -> Response:
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data, ignore_warnings=ignore_warnings)

    @access("core_admin", "event_admin")
    @REQUESTdata("download", "is_search")
    def user_search(self, rs: RequestState, download: Optional[str],
                    is_search: bool) -> Response:
        """Perform search."""
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        return self.generic_user_search(
            rs, download, is_search, 'qview_event_user', 'qview_event_user',
            self.eventproxy.submit_general_query, choices=choices)

    @access("core_admin", "event_admin")
    @REQUESTdata("download", "is_search")
    def archived_user_search(self, rs: RequestState, download: Optional[str],
                             is_search: bool) -> Response:
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': OrderedDict(
                xsorted(events.items(), key=operator.itemgetter(1))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        return self.generic_user_search(
            rs, download, is_search,
            'qview_archived_past_event_user', 'qview_archived_persona',
            self.eventproxy.submit_general_query, choices=choices,
            endpoint="archived_user_search")

    @access("anonymous")
    def list_events(self, rs: RequestState) -> Response:
        """List all events organized via DB."""
        events = self.eventproxy.list_events(rs)
        events = self.eventproxy.get_events(rs, events.keys())
        if self.is_admin(rs):
            for event in events.values():
                regs = self.eventproxy.list_registrations(rs, event['id'])
                event['registrations'] = len(regs)

        def querylink(event_id: int) -> str:
            query = Query(
                "qview_registration",
                self.make_registration_query_spec(events[event_id]),
                ("persona.given_names", "persona.family_name"),
                (),
                (("persona.family_name", True), ("persona.given_names", True)))
            params = querytoparams_filter(query)
            params['is_search'] = True
            params['event_id'] = event_id
            return cdedburl(rs, 'event/registration_query', params)

        return self.render(rs, "list_events",
                           {'events': events, 'querylink': querylink})

    @access("anonymous")
    def show_event(self, rs: RequestState, event_id: int) -> Response:
        """Display event organized via DB."""
        params: CdEDBObject = {}
        if "event" in rs.user.roles:
            params['orgas'] = OrderedDict(
                (e['id'], e) for e in xsorted(
                    self.coreproxy.get_personas(
                        rs, rs.ambience['event']['orgas']).values(),
                    key=EntitySorter.persona))
        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs.ambience['event'])
            params['participant_list'] = self.mlproxy.verify_existence(
                rs, ml_type.get_full_address(ml_data))
        if event_id in rs.user.orga or self.is_admin(rs):
            params['institutions'] = self.pasteventproxy.list_institutions(rs)
            params['minor_form_present'] = (
                    self.eventproxy.get_minor_form(rs, event_id) is not None)
        elif not rs.ambience['event']['is_visible']:
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        return self.render(rs, "show_event", params)

    @access("anonymous")
    def course_list(self, rs: RequestState, event_id: int) -> Response:
        """List courses from an event."""
        if (not rs.ambience['event']['is_course_list_visible']
                and not (event_id in rs.user.orga or self.is_admin(rs))):
            rs.notify("warning", n_("Course list not published yet."))
            return self.redirect(rs, "event/show_event")
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = None
        if course_ids:
            courses = self.eventproxy.get_courses(rs, course_ids.keys())
        return self.render(rs, "course_list", {'courses': courses})

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
        return self.render(rs, "participant_list", data)

    def _get_participant_list_data(
            self, rs: RequestState, event_id: int,
            part_ids: Collection[int] = (),
            sortkey: str = "persona", reverse: bool = False) -> CdEDBObject:
        """This provides data for download and online participant list.

        This is un-inlined so download_participant_list can use this
        as well."""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
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
        return self.render(rs, "participant_info")

    @access("event")
    @event_guard()
    def change_event_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        merge_dicts(rs.values, rs.ambience['event'])

        sorted_fields = xsorted(rs.ambience['event']['fields'].values(),
                                key=EntitySorter.event_field)
        lodge_fields = [
            (field['id'], field['field_name']) for field in sorted_fields
            if field['association'] == const.FieldAssociations.registration
            and field['kind'] == const.FieldDatatypes.str
        ]
        camping_mat_fields = [
            (field['id'], field['field_name']) for field in sorted_fields
            if field['association'] == const.FieldAssociations.registration
            and field['kind'] == const.FieldDatatypes.bool
        ]
        course_room_fields = [
            (field['id'], field['field_name']) for field in sorted_fields
            if field['association'] == const.FieldAssociations.course
            and field['kind'] == const.FieldDatatypes.str
        ]
        return self.render(rs, "change_event", {
            'institutions': institutions,
            'accounts': self.conf["EVENT_BANK_ACCOUNTS"],
            'lodge_fields': lodge_fields,
            'camping_mat_fields': camping_mat_fields,
            'course_room_fields': course_room_fields})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*EVENT_EXPOSED_FIELDS)
    def change_event(self, rs: RequestState, event_id: int, data: CdEDBObject
                     ) -> Response:
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, vtypes.Event, data)
        if rs.has_validation_errors():
            return self.change_event_form(rs, event_id)
        assert data is not None

        code = self.eventproxy.set_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    def get_minor_form(self, rs: RequestState, event_id: int) -> Response:
        """Retrieve minor form."""
        if not (rs.ambience['event']['is_visible']
                or event_id in rs.user.orga
                or self.is_admin(rs)):
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        minor_form = self.eventproxy.get_minor_form(rs, event_id)
        return self.send_file(
            rs, data=minor_form, mimetype="application/pdf",
            filename="{}_minor_form.pdf".format(
                rs.ambience['event']['shortname']))

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("minor_form")
    @REQUESTdata("delete")
    def change_minor_form(self, rs: RequestState, event_id: int,
                          minor_form: werkzeug.datastructures.FileStorage, delete: bool
                          ) -> Response:
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check_optional(
            rs, vtypes.PDFFile, minor_form, "minor_form")
        if not minor_form and not delete:
            rs.append_validation_error(
                ("minor_form", ValueError(n_("Must not be empty."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.change_minor_form(rs, event_id, minor_form)
        self.notify_return_code(rs, code, success=n_("Minor form updated."),
                                info=n_("Minor form has been removed."),
                                error=n_("Nothing to remove."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("orga_id")
    def add_orga(self, rs: RequestState, event_id: int, orga_id: vtypes.CdedbID
                 ) -> Response:
        """Make an additional persona become orga."""
        if rs.has_validation_errors():
            # Shortcircuit if we have got no workable cdedbid
            return self.show_event(rs, event_id)
        if not self.coreproxy.verify_id(rs, orga_id, is_archived=False):
            rs.append_validation_error(
                ('orga_id',
                 ValueError(n_("This user does not exist or is archived."))))
        if not self.coreproxy.verify_persona(rs, orga_id, {"event"}):
            rs.append_validation_error(
                ('orga_id', ValueError(n_("This user is not an event user."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.add_event_orgas(rs, event_id, {orga_id})
        self.notify_return_code(rs, code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("orga_id")
    def remove_orga(self, rs: RequestState, event_id: int, orga_id: vtypes.ID
                    ) -> Response:
        """Remove a persona as orga of an event.

        This is only available for admins. This can drop your own orga role.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        code = self.eventproxy.remove_event_orga(rs, event_id, orga_id)
        self.notify_return_code(rs, code, error=n_("Action had no effect."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTdata("orgalist")
    def create_event_mailinglist(self, rs: RequestState, event_id: int,
                                 orgalist: bool = False) -> Response:
        """Create a default mailinglist for the event."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not rs.ambience['event']['orgas']:
            rs.notify('error',
                      n_("Must have orgas in order to create a mailinglist."))
            return self.redirect(rs, "event/show_event")

        ml_data = self._get_mailinglist_setter(rs.ambience['event'], orgalist)
        ml_address = ml_type.get_full_address(ml_data)
        if not self.mlproxy.verify_existence(rs, ml_address):
            if not orgalist:
                link = cdedburl(rs, "event/register", {'event_id': event_id})
                ml_data['description'] = ml_data['description'].format(link)
            code = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Orga mailinglist created.") if orgalist
                   else n_("Participant mailinglist created."))
            self.notify_return_code(rs, code, success=msg)
            if code and orgalist:
                data = {'id': event_id, 'orga_address': ml_address}
                self.eventproxy.set_event(rs, data)
        else:
            rs.notify("info", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_address})
        return self.redirect(rs, "event/show_event")

    def _deletion_blocked_parts(self, rs: RequestState, event_id: int) -> Set[int]:
        """All parts of a given event which must not be deleted."""
        blocked_parts: Set[int] = set()
        if len(rs.ambience['event']['parts']) == 1:
            blocked_parts.add(unwrap(rs.ambience['event']['parts'].keys()))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        # referenced tracks block part deletion
        for course in courses.values():
            for track_id in course['segments']:
                blocked_parts.add(rs.ambience['event']['tracks'][track_id]['part_id'])
        return blocked_parts

    def _deletion_blocked_tracks(self, rs: RequestState, event_id: int) -> Set[int]:
        """All tracks of a given event which must not be deleted."""
        blocked_tracks: Set[int] = set()
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        for course in courses.values():
            blocked_tracks.update(course['segments'])
        return blocked_tracks

    @access("event")
    @event_guard()
    def part_summary(self, rs: RequestState, event_id: int) -> Response:
        """Display a comprehensive overview of all parts of a given event."""
        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        referenced_parts = self._deletion_blocked_parts(rs, event_id)

        fee_modifiers_by_part = {
            part_id: {
                e['id']: e
                for e in rs.ambience['event']['fee_modifiers'].values()
                if e['part_id'] == part_id
            }
            for part_id in rs.ambience['event']['parts']
        }

        return self.render(rs, "part_summary", {
            'fee_modifiers_by_part': fee_modifiers_by_part,
            'referenced_parts': referenced_parts,
            'has_registrations': has_registrations})

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTdata("ack_delete")
    def delete_part(self, rs: RequestState, event_id: int, part_id: int,
                    ack_delete: bool) -> Response:
        """Delete a given part."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.part_summary(rs, event_id)
        if self.eventproxy.has_registrations(rs, event_id):
            raise ValueError(n_("Registrations exist, no deletion."))
        if part_id in self._deletion_blocked_parts(rs, event_id):
            raise ValueError(n_("This part can not be deleted."))

        event = {
            'id': event_id,
            'parts': {part_id: None},
        }
        code = self.eventproxy.set_event(rs, event)
        self.notify_return_code(rs, code)

        return self.redirect(rs, "event/part_summary")

    @access("event")
    @event_guard()
    def change_part_form(self, rs: RequestState, event_id: int, part_id: int) -> Response:
        part = rs.ambience['event']['parts'][part_id]

        current = copy.deepcopy(part)
        del current['id']
        del current['tracks']
        for track_id, track in part['tracks'].items():
            for k in ('title', 'shortname', 'num_choices', 'min_choices', 'sortkey'):
                current[f"track_{k}_{track_id}"] = track[k]
        for m in rs.ambience['event']['fee_modifiers'].values():
            for k in ('modifier_name', 'amount', 'field_id'):
                current[f"fee_modifier_{k}_{m['id']}"] = m[k]
        merge_dicts(rs.values, current)

        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        referenced_tracks = self._deletion_blocked_tracks(rs, event_id)

        sorted_fields = xsorted(rs.ambience['event']['fields'].values(),
                                key=EntitySorter.event_field)
        legal_datatypes, legal_assocs = EVENT_FIELD_SPEC['fee_modifier']
        fee_modifier_fields = [
            (field['id'], field['field_name']) for field in sorted_fields
            if field['association'] in legal_assocs and field['kind'] in legal_datatypes
        ]
        fee_modifiers = {
            e['id']: e
            for e in rs.ambience['event']['fee_modifiers'].values()
            if e['part_id'] == part_id
        }
        legal_datatypes, legal_assocs = EVENT_FIELD_SPEC['waitlist']
        waitlist_fields = [
            (field['id'], field['field_name']) for field in sorted_fields
            if field['association'] in legal_assocs and field['kind'] in legal_datatypes
        ]
        return self.render(rs, "change_part", {
            'part_id': part_id,
            'fee_modifier_fields': fee_modifier_fields,
            'fee_modifiers': fee_modifiers,
            'waitlist_fields': waitlist_fields,
            'referenced_tracks': referenced_tracks,
            'has_registrations': has_registrations,
            'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*EVENT_PART_COMMON_FIELDS)
    def change_part(self, rs: RequestState, event_id: int, part_id: int,
                    data: CdEDBObject) -> Response:
        """Change one part, including the associated tracks and fee modifiers."""
        # this will be added at the end after processing the dynamic input and will only
        # yield false validation errors
        del data['tracks']
        data = check(rs, vtypes.EventPart, data)
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        def track_constraint_maker(track_id: int, prefix: str) -> List[RequestConstraint]:
            min_choice = f"{prefix}min_choices_{track_id}"
            num_choice = f"{prefix}num_choices_{track_id}"
            msg = n_("Must be less or equal than total Course Choices.")
            return [(
                lambda d: d[min_choice] <= d[num_choice], (min_choice, ValueError(msg))
            )]

        #
        # process the dynamic track input
        #
        track_existing = rs.ambience['event']['parts'][part_id]['tracks']
        track_spec = {
            'title': str,
            'shortname': str,
            'num_choices': vtypes.NonNegativeInt,
            'min_choices': vtypes.NonNegativeInt,
            'sortkey': int
        }
        track_data = process_dynamic_input(
            rs, track_existing, track_spec, prefix="track",
            constraint_maker=track_constraint_maker)

        deleted_tracks = {anid for anid in track_data if track_data[anid] is None}
        new_tracks = {anid for anid in track_data if anid < 0}
        if deleted_tracks and has_registrations:
            raise ValueError(n_("Registrations exist, no track deletion possible."))
        if deleted_tracks & self._deletion_blocked_tracks(rs, event_id):
            raise ValueError(n_("Some tracks can not be deleted."))
        if new_tracks and has_registrations:
            raise ValueError(n_("Registrations exist, no track creation possible."))

        def fee_modifier_constraint_maker(
                fee_modifier_id: int, prefix: str) -> List[RequestConstraint]:
            key = f"{prefix}field_id_{fee_modifier_id}"
            fields = rs.ambience['event']['fields']
            legal_datatypes, legal_assocs = EVENT_FIELD_SPEC['fee_modifier']
            msg = n_("Fee Modifier linked to non-fitting field.")
            return [(
                lambda d: (fields[d[key]]['association'] in legal_assocs
                           and fields[d[key]]['kind'] in legal_datatypes),
                (key, ValueError(msg))
            )]

        #
        # process the dynamic fee modifier input
        #
        fee_modifier_existing = [
            mod['id'] for mod in rs.ambience['event']['fee_modifiers'].values()
            if mod['part_id'] == part_id
        ]
        fee_modifier_spec = {
            'modifier_name': vtypes.RestrictiveIdentifier,
            'amount': decimal.Decimal,
            'field_id': vtypes.ID,
        }
        # do not change fee modifiers once registrations exist
        if has_registrations:
            fee_modifier_data = dict()
        else:
            fee_modifier_data = process_dynamic_input(
                rs, fee_modifier_existing, fee_modifier_spec, prefix="fee_modifier",
                additional={'part_id': part_id},
                constraint_maker=fee_modifier_constraint_maker)

        # Check if each linked field and fee modifier name is unique.
        used_fields: Set[int] = set()
        used_names: Set[str] = set()
        field_msg = n_("Must not have multiple fee modifiers linked to the same"
                       " field in one event part.")
        name_msg = n_("Must not have multiple fee modifiers with he same name "
                      "in one event part.")
        for modifier_id, modifier in fee_modifier_data.items():
            if modifier is None:
                continue
            if modifier['field_id'] in used_fields:
                rs.append_validation_error(
                    (f"fee_modifier_field_id_{modifier_id}", ValueError(field_msg))
                )
            if modifier['modifier_name'] in used_names:
                rs.append_validation_error(
                    (f"fee_modifier_modifier_name_{modifier_id}", ValueError(name_msg))
                )
            used_fields.add(modifier['field_id'])
            used_names.add(modifier['modifier_name'])

        if rs.has_validation_errors():
            return self.change_part_form(rs, event_id, part_id)

        #
        # put it all together
        #
        data['tracks'] = track_data
        fee_modifiers = rs.ambience['event']['fee_modifiers']
        fee_modifiers.update(fee_modifier_data)
        event = {
            'id': event_id,
            'parts': {part_id: data},
            'fee_modifiers': fee_modifiers,
        }
        code = self.eventproxy.set_event(rs, event)
        self.notify_return_code(rs, code)

        return self.redirect(rs, "event/part_summary")

    @access("event")
    @event_guard()
    def field_summary_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        formatter = lambda k, v: (v if k != 'entries' or not v else
                                  '\n'.join(';'.join(line) for line in v))
        current = {
            "{}_{}".format(key, field_id): formatter(key, value)
            for field_id, field in rs.ambience['event']['fields'].items()
            for key, value in field.items() if key != 'id'}
        merge_dicts(rs.values, current)
        referenced = set()
        fee_modifiers = set()
        full_questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        for v in full_questionnaire.values():
            for row in v:
                if row['field_id']:
                    referenced.add(row['field_id'])
        if rs.ambience['event']['lodge_field']:
            referenced.add(rs.ambience['event']['lodge_field'])
        if rs.ambience['event']['camping_mat_field']:
            referenced.add(rs.ambience['event']['camping_mat_field'])
        if rs.ambience['event']['course_room_field']:
            referenced.add(rs.ambience['event']['course_room_field'])
        for mod in rs.ambience['event']['fee_modifiers'].values():
            referenced.add(mod['field_id'])
            fee_modifiers.add(mod['field_id'])
        for part in rs.ambience['event']['parts'].values():
            if part['waitlist_field']:
                referenced.add(part['waitlist_field'])
        return self.render(rs, "field_summary", {
            'referenced': referenced, 'fee_modifiers': fee_modifiers})

    @staticmethod
    def process_field_input(rs: RequestState, fields: CdEDBObjectMap
                            ) -> CdEDBOptionalMap:
        """This handles input to configure the fields.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.
        """
        delete_flags = request_extractor(
            rs, {f"delete_{field_id}": bool for field_id in fields})
        deletes = {field_id for field_id in fields
                   if delete_flags['delete_{}'.format(field_id)]}
        ret: CdEDBOptionalMap = {}

        def params_a(anid: int) -> TypeMapping:
            return {
                f"kind_{anid}": const.FieldDatatypes,
                f"association_{anid}": const.FieldAssociations,
                f"entries_{anid}": Optional[str],  # type: ignore
            }
        for field_id in fields:
            if field_id not in deletes:
                tmp: Optional[CdEDBObject] = request_extractor(rs, params_a(field_id))
                if rs.has_validation_errors():
                    break
                tmp = check(rs, vtypes.EventField, tmp,
                            extra_suffix="_{}".format(field_id))
                if tmp:
                    temp = {
                        'kind': tmp["kind_{}".format(field_id)],
                        'association': tmp["association_{}".format(field_id)],
                        'entries': tmp["entries_{}".format(field_id)]}
                    ret[field_id] = temp
        for field_id in deletes:
            ret[field_id] = None
        marker = 1

        def params_b(anid: int) -> TypeMapping:
            return {
                f"field_name_-{anid}": str,
                f"kind_-{anid}": const.FieldDatatypes,
                f"association_-{anid}": const.FieldAssociations,
                f"entries_-{anid}": Optional[str],  # type: ignore
            }
        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(
                rs, {f"create_-{marker}": bool}))
            if will_create:
                tmp = request_extractor(rs, params_b(marker))
                if rs.has_validation_errors():
                    marker += 1
                    break
                tmp = check(rs, vtypes.EventField, tmp, creation=True,
                            extra_suffix="_-{}".format(marker))
                if tmp:
                    temp = {
                        'field_name': tmp["field_name_-{}".format(marker)],
                        'kind': tmp["kind_-{}".format(marker)],
                        'association': tmp["association_-{}".format(marker)],
                        'entries': tmp["entries_-{}".format(marker)]}
                    ret[-marker] = temp
            else:
                break
            marker += 1

        def field_name(field_id: int, field: Optional[CdEDBObject]) -> str:
            return (field['field_name'] if field and 'field_name' in field
                    else fields[field_id]['field_name'])
        count = Counter(field_name(f_id, field) for f_id, field in ret.items())
        for field_id, field in ret.items():
            if field and count.get(field_name(field_id, field), 0) > 1:
                rs.append_validation_error(
                    ("field_name_{}".format(field_id),
                      ValueError(n_("Field name not unique."))))
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("active_tab")
    def field_summary(self, rs: RequestState, event_id: int, active_tab: Optional[str]
                      ) -> Response:
        """Manipulate the fields of an event."""
        fields = self.process_field_input(
            rs, rs.ambience['event']['fields'])
        if rs.has_validation_errors():
            return self.field_summary_form(rs, event_id)
        for field_id, field in rs.ambience['event']['fields'].items():
            if fields.get(field_id) == field:
                # remove unchanged
                del fields[field_id]
        event = {
            'id': event_id,
            'fields': fields
        }
        code = self.eventproxy.set_event(rs, event)
        self.notify_return_code(rs, code)
        return self.redirect(
            rs, "event/field_summary_form", anchor=(
                ("tab:" + active_tab) if active_tab is not None else None))

    @staticmethod
    def _get_mailinglist_setter(event: CdEDBObject, orgalist: bool = False
                                ) -> CdEDBObject:
        # During event creation the id is not yet known.
        event_id = event.get('id')
        if orgalist:
            descr = ("Bitte wende Dich bei Fragen oder Problemen, die mit"
                     " unserer Veranstaltung zusammenhängen, über diese Liste"
                     " an uns.")
            orga_ml_data = {
                'title': f"{event['title']} Orgateam",
                'local_part': f"{event['shortname'].lower()}",
                'domain': const.MailinglistDomain.aka,
                'description': descr,
                'mod_policy': const.ModerationPolicy.unmoderated,
                'attachment_policy': const.AttachmentPolicy.allow,
                'subject_prefix': event['shortname'],
                'maxsize': ml_type.EventOrgaMailinglist.maxsize_default,
                'is_active': True,
                'event_id': event_id,
                'notes': None,
                'moderators': event['orgas'],
                'ml_type': const.MailinglistTypes.event_orga,
            }
            return orga_ml_data
        else:
            descr = ("Dieser Liste kannst Du nur beitreten, indem Du Dich zu "
                     "unserer [Veranstaltung anmeldest]({}) und den Status "
                     "*Teilnehmer* erhälst. Auf dieser Liste stehen alle "
                     "Teilnehmer unserer Veranstaltung; sie kann im Vorfeld "
                     "zum Austausch untereinander genutzt werden.")
            participant_ml_data = {
                'title': f"{event['title']} Teilnehmer",
                'local_part': f"{event['shortname'].lower()}-all",
                'domain': const.MailinglistDomain.aka,
                'description': descr,
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'attachment_policy': const.AttachmentPolicy.pdf_only,
                'subject_prefix': event['shortname'],
                'maxsize': ml_type.EventAssociatedMailinglist.maxsize_default,
                'is_active': True,
                'event_id': event_id,
                'registration_stati': [const.RegistrationPartStati.participant],
                'notes': None,
                'moderators': event['orgas'],
                'ml_type': const.MailinglistTypes.event_associated,
            }
            return participant_ml_data

    @access("event_admin")
    def create_event_form(self, rs: RequestState) -> Response:
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        return self.render(rs, "create_event",
                           {'institutions': institutions,
                            'accounts': self.conf["EVENT_BANK_ACCOUNTS"]})

    @access("event_admin", modi={"POST"})
    @REQUESTdata("part_begin", "part_end", "orga_ids", "create_track",
                 "create_orga_list", "create_participant_list")
    @REQUESTdatadict(*EVENT_EXPOSED_FIELDS)
    def create_event(self, rs: RequestState, part_begin: datetime.date,
                     part_end: datetime.date, orga_ids: vtypes.CdedbIDList,
                     create_track: bool, create_orga_list: bool,
                     create_participant_list: bool, data: CdEDBObject
                     ) -> Response:
        """Create a new event, organized via DB."""
        # multi part events will have to edit this later on
        data["orgas"] = orga_ids
        new_track = {
            'title': data['title'],
            'shortname': data['shortname'],
            'num_choices': DEFAULT_NUM_COURSE_CHOICES,
            'min_choices': DEFAULT_NUM_COURSE_CHOICES,
            'sortkey': 1}
        data['parts'] = {
            -1: {
                'title': data['title'],
                'shortname': data['shortname'],
                'part_begin': part_begin,
                'part_end': part_end,
                'fee': decimal.Decimal(0),
                'waitlist_field': None,
                'tracks': ({-1: new_track} if create_track else {}),
            }
        }
        data = check(rs, vtypes.Event, data, creation=True)
        if orga_ids:
            if not self.coreproxy.verify_ids(rs, orga_ids, is_archived=False):
                rs.append_validation_error(
                    ('orga_ids', ValueError(
                        n_("Some of these users do not exist or are archived.")
                    ))
                )
            if not self.coreproxy.verify_personas(rs, orga_ids, {"event"}):
                rs.append_validation_error(
                    ('orga_ids', ValueError(
                        n_("Some of these users are not event users.")
                    ))
                )
        else:
            if create_orga_list or create_participant_list:
                # mailinglists require moderators
                rs.append_validation_error(
                    ("orga_ids", ValueError(
                        n_("Must not be empty in order to create a mailinglist.")
                    ))
                )
        if rs.has_validation_errors():
            return self.create_event_form(rs)
        assert data is not None

        orga_ml_data = None
        orga_ml_address = None
        if create_orga_list:
            orga_ml_data = self._get_mailinglist_setter(data, orgalist=True)
            orga_ml_address = ml_type.get_full_address(orga_ml_data)
            data['orga_address'] = orga_ml_address
            if self.mlproxy.verify_existence(rs, orga_ml_address):
                orga_ml_data = None
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': orga_ml_address})
        else:
            data['orga_address'] = None

        new_id = self.eventproxy.create_event(rs, data)
        if orga_ml_data:
            orga_ml_data['event_id'] = new_id
            code = self.mlproxy.create_mailinglist(rs, orga_ml_data)
            self.notify_return_code(
                rs, code, success=n_("Orga mailinglist created."))
        if create_participant_list:
            participant_ml_data = self._get_mailinglist_setter(data)
            participant_ml_address = ml_type.get_full_address(participant_ml_data)
            if not self.mlproxy.verify_existence(rs, participant_ml_address):
                link = cdedburl(rs, "event/register", {'event_id': new_id})
                descr = participant_ml_data['description'].format(link)
                participant_ml_data['description'] = descr
                participant_ml_data['event_id'] = new_id
                code = self.mlproxy.create_mailinglist(rs, participant_ml_data)
                self.notify_return_code(
                    rs, code, success=n_("Participant mailinglist created."))
            else:
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': participant_ml_address})
        self.notify_return_code(rs, new_id, success=n_("Event created."))
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event")
    @event_guard()
    def show_course(self, rs: RequestState, event_id: int, course_id: int
                    ) -> Response:
        """Display course associated to event organized via DB."""
        params: CdEDBObject = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            all_registrations = self.eventproxy.get_registrations(
                rs, registration_ids)
            registrations = {
                k: v
                for k, v in all_registrations.items()
                if any(course_id in {track['course_id'], track['course_instructor']}
                       for track in v['tracks'].values())
            }
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
            attendees = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas, instructors=True)
            learners = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas, instructors=False)
            params['personas'] = personas
            params['registrations'] = registrations
            params['attendees'] = attendees
            params['learners'] = learners
            params['blockers'] = self.eventproxy.delete_course_blockers(
                rs, course_id).keys() - {"instructors", "course_choices",
                                         "course_segments"}
            instructor_ids = {reg['persona_id']
                              for reg in all_registrations.values()
                              if any(t['course_instructor'] == course_id
                                     for t in reg['tracks'].values())}
            instructors = self.coreproxy.get_personas(rs, instructor_ids)
            params['instructor_emails'] = [p['username']
                                           for p in instructors.values()]
        return self.render(rs, "show_course", params)

    @access("event")
    @event_guard(check_offline=True)
    def change_course_form(self, rs: RequestState, event_id: int, course_id: int
                           ) -> Response:
        """Render form."""
        if 'segments' not in rs.values:
            rs.values.setlist('segments', rs.ambience['course']['segments'])
        if 'active_segments' not in rs.values:
            rs.values.setlist('active_segments',
                              rs.ambience['course']['active_segments'])
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['course']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['course'], field_values)
        return self.render(rs, "change_course")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*COURSE_COMMON_FIELDS)
    @REQUESTdata("segments", "active_segments")
    def change_course(self, rs: RequestState, event_id: int, course_id: int,
                      segments: Collection[int],
                      active_segments: Collection[int], data: CdEDBObject
                      ) -> Response:
        """Modify a course associated to an event organized via DB."""
        data['id'] = course_id
        data['segments'] = segments
        data['active_segments'] = active_segments
        field_params: TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, vtypes.Course, data)
        if rs.has_validation_errors():
            return self.change_course_form(rs, event_id, course_id)
        assert data is not None
        code = self.eventproxy.set_course(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @access("event")
    @event_guard(check_offline=True)
    def create_course_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        # by default select all tracks
        tracks = rs.ambience['event']['tracks']
        if not tracks:
            rs.notify("error", n_("Event without tracks forbids courses."))
            return self.redirect(rs, 'event/course_stats')
        if 'segments' not in rs.values:
            rs.values.setlist('segments', tracks)
        return self.render(rs, "create_course")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*COURSE_COMMON_FIELDS)
    @REQUESTdata("segments")
    def create_course(self, rs: RequestState, event_id: int,
                      segments: Collection[int], data: CdEDBObject) -> Response:
        """Create a new course associated to an event organized via DB."""
        data['event_id'] = event_id
        data['segments'] = segments
        field_params: TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, vtypes.Course, data, creation=True)
        if rs.has_validation_errors():
            return self.create_course_form(rs, event_id)
        assert data is not None

        new_id = self.eventproxy.create_course(rs, data)
        self.notify_return_code(rs, new_id, success=n_("Course created."))
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_course(self, rs: RequestState, event_id: int, course_id: int,
                      ack_delete: bool) -> Response:
        """Delete a course from an event organized via DB."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_course(rs, event_id, course_id)
        blockers = self.eventproxy.delete_course_blockers(rs, course_id)
        # Do not allow deletion of course with attendees
        if "attendees" in blockers:
            rs.notify("error", n_("Course cannot be deleted, because it still "
                                  "has attendees."))
            return self.redirect(rs, "event/show_course")
        code = self.eventproxy.delete_course(
            rs, course_id, {"instructors", "course_choices", "course_segments"})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/course_stats")

    @access("event")
    @event_guard()
    def stats(self, rs: RequestState, event_id: int) -> Response:
        """Present an overview of the basic stats."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        stati = const.RegistrationPartStati
        get_age = lambda u, p: determine_age_class(
            u['birthday'],
            rs.ambience['event']['parts'][p['part_id']]['part_begin'])

        # Tests for participant/registration statistics.
        # `e` is the event, `r` is a registration, `p` is a registration_part.
        tests1 = OrderedDict((
            ('pending', (lambda e, r, p: (
                    p['status'] == stati.applied))),
            (' payed', (lambda e, r, p: (
                    p['status'] == stati.applied
                    and r['payment']))),
            ('participant', (lambda e, r, p: (
                    p['status'] == stati.participant))),
            (' all minors', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p).is_minor())))),
            (' u16', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p)
                         == AgeClasses.u16)))),
            (' u14', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']], p)
                         == AgeClasses.u14)))),
            (' checked in', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and r['checkin']))),
            (' not checked in', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and not r['checkin']))),
            (' orgas', (lambda e, r, p: (
                    p['status'] == stati.participant
                    and r['persona_id'] in e['orgas']))),
            ('waitlist', (lambda e, r, p: (
                    p['status'] == stati.waitlist))),
            ('guest', (lambda e, r, p: (
                    p['status'] == stati.guest))),
            ('total involved', (lambda e, r, p: (
                stati(p['status']).is_involved()))),
            (' not payed', (lambda e, r, p: (
                    stati(p['status']).is_involved()
                    and not r['payment']))),
            (' no parental agreement', (lambda e, r, p: (
                    stati(p['status']).is_involved()
                    and get_age(personas[r['persona_id']], p).is_minor()
                    and not r['parental_agreement']))),
            ('no lodgement', (lambda e, r, p: (
                    stati(p['status']).is_present()
                    and not p['lodgement_id']))),
            ('cancelled', (lambda e, r, p: (
                    p['status'] == stati.cancelled))),
            ('rejected', (lambda e, r, p: (
                    p['status'] == stati.rejected))),
            ('total', (lambda e, r, p: (
                    p['status'] != stati.not_applied))),
        ))
        per_part_statistics: Dict[str, Dict[int, int]] = OrderedDict()
        for key, test1 in tests1.items():
            per_part_statistics[key] = {
                part_id: sum(
                    1 for r in registrations.values()
                    if test1(rs.ambience['event'], r, r['parts'][part_id]))
                for part_id in rs.ambience['event']['parts']}

        # Test for course statistics
        # `c` is a course, `t` is a track.
        tests2 = OrderedDict((
            ('courses', lambda c, t: (
                    t in c['segments'])),
            ('cancelled courses', lambda c, t: (
                    t in c['segments']
                    and t not in c['active_segments'])),
        ))

        # Tests for course attendee statistics
        # `e` is the event, `r` is the registration, `p` is a event_part,
        # `t` is a track.
        tests3 = OrderedDict((
            ('all instructors', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_instructor']))),
            ('instructors', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_id']
                    and t['course_id'] == t['course_instructor']))),
            ('attendees', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_id']
                    and t['course_id'] != t['course_instructor']))),
            ('no course', (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and not t['course_id']
                    and r['persona_id'] not in e['orgas']))),))
        per_track_statistics: Dict[str, Dict[int, Optional[int]]] = OrderedDict()
        regs_in_choice_x: Dict[str, Dict[int, List[int]]] = OrderedDict()
        if tracks:
            # Additional dynamic tests for course attendee statistics
            for i in range(max(t['num_choices'] for t in tracks.values())):
                key = rs.gettext('In {}. Choice').format(i + 1)
                checker = (
                    functools.partial(
                        lambda p, t, j: (
                            p['status'] == stati.participant
                            and t['course_id']
                            and len(t['choices']) > j
                            and (t['choices'][j] == t['course_id'])),
                        j=i))
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if checker(r['parts'][tracks[track_id]['part_id']],
                                   r['tracks'][track_id]))
                    if i < tracks[track_id]['num_choices'] else None
                    for track_id in tracks
                }

                # the ids are used later on for the query page
                regs_in_choice_x[key] = {
                    track_id: [
                        r['id'] for r in registrations.values()
                        if checker(r['parts'][tracks[track_id]['part_id']],
                                   r['tracks'][track_id])
                    ]
                    for track_id in tracks
                }

            for key, test2 in tests2.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for c in courses.values()
                        if test2(c, track_id))
                    for track_id in tracks}
            for key, test3 in tests3.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if test3(rs.ambience['event'], r,
                                r['parts'][tracks[track_id]['part_id']],
                                r['tracks'][track_id]))
                    for track_id in tracks}

        # The base query object to use for links to event/registration_query
        base_registration_query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"],
            [],
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        base_course_query = Query(
            "qview_course",
            self.make_course_query_spec(rs.ambience['event']),
            ["course.nr", "course.shortname"],
            [],
            (("course.nr", True), ("course.shortname", True),)
        )
        # Some reusable query filter definitions
        involved_filter = lambda p: (
            'part{}.status'.format(p['id']),
            QueryOperators.oneof,
            [x.value for x in stati if x.is_involved()],
        )
        participant_filter = lambda p: (
            'part{}.status'.format(p['id']),
            QueryOperators.equal,
            stati.participant.value,
        )
        QueryFilterGetter = Callable[
            [CdEDBObject, CdEDBObject, CdEDBObject], Collection[QueryConstraint]]
        # Query filters for all the registration statistics defined and calculated above.
        # They are customized and inserted into the query on the fly by get_query().
        # `e` is the event, `p` is the event_part, `t` is the track.
        registration_query_filters: Dict[str, QueryFilterGetter] = {
            'pending': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.applied.value),),
            ' payed': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.applied.value),
                ("reg.payment", QueryOperators.nonempty, None),),
            'participant': lambda e, p, t: (participant_filter(p),),
            ' all minors': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 (deduct_years(p['part_begin'], 18)))),
            ' u18': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.between,
                 (deduct_years(p['part_begin'], 18)
                    + datetime.timedelta(days=1),
                  deduct_years(p['part_begin'], 16)),),),
            ' u16': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.between,
                 (deduct_years(p['part_begin'], 16)
                    + datetime.timedelta(days=1),
                  deduct_years(p['part_begin'], 14)),),),
            ' u14': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(p['part_begin'], 14)),),
            ' checked in': lambda e, p, t: (
                participant_filter(p),
                ("reg.checkin", QueryOperators.nonempty, None),),
            ' not checked in': lambda e, p, t: (
                participant_filter(p),
                ("reg.checkin", QueryOperators.empty, None),),
            ' orgas': lambda e, p, t: (
                ('persona.id', QueryOperators.oneof,
                 rs.ambience['event']['orgas']),),
            'waitlist': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.waitlist.value),),
            'guest': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.guest.value),),
            'total involved': lambda e, p, t: (involved_filter(p),),
            ' not payed': lambda e, p, t: (
                involved_filter(p),
                ("reg.payment", QueryOperators.empty, None),),
            ' no parental agreement': lambda e, p, t: (
                involved_filter(p),
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(p['part_begin'], 18)),
                ("reg.parental_agreement", QueryOperators.equal, False),),
            'no lodgement': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.oneof,
                 [x.value for x in stati if x.is_present()]),
                ('lodgement{}.id'.format(p['id']),
                 QueryOperators.empty, None)),
            'cancelled': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.cancelled.value),),
            'rejected': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.equal,
                 stati.rejected.value),),
            'total': lambda e, p, t: (
                ('part{}.status'.format(p['id']), QueryOperators.unequal,
                 stati.not_applied.value),),

            'all instructors': lambda e, p, t: (
                participant_filter(p),
                ('course_instructor{}.id'.format(t['id']),
                 QueryOperators.nonempty, None),),
            'instructors': lambda e, p, t: (
                participant_filter(p),
                ('track{}.is_course_instructor'.format(t['id']),
                 QueryOperators.equal, True),),
            'attendees': lambda e, p, t: (
                participant_filter(p),
                (f'course{t["id"]}.id', QueryOperators.nonempty, None),
                (f'track{t["id"]}.is_course_instructor',
                 QueryOperators.equalornull, False),),
            'no course': lambda e, p, t: (
                participant_filter(p),
                ('course{}.id'.format(t['id']),
                 QueryOperators.empty, None),
                ('persona.id', QueryOperators.otherthan,
                 rs.ambience['event']['orgas']),)
        }
        for name, track_regs in regs_in_choice_x.items():
            registration_query_filters[name] = functools.partial(
                lambda e, p, t, t_r: (
                    ("reg.id", QueryOperators.oneof, t_r[t['id']]),
                ), t_r=track_regs
            )
        # Query filters for all the course statistics defined and calculated above.
        # They are customized and inserted into the query on the fly by get_query().
        # `e` is the event, `p` is the event_part, `t` is the track.
        course_query_filters: Dict[str, QueryFilterGetter] = {
            'courses': lambda e, p, t: (
                (f'track{t["id"]}.is_offered', QueryOperators.equal, True),),
            'cancelled courses': lambda e, p, t: (
                (f'track{t["id"]}.is_offered', QueryOperators.equal, True),
                (f'track{t["id"]}.takes_place', QueryOperators.equal, False),),
        }

        query_additional_fields: Dict[str, Collection[str]] = {
            ' payed': ('reg.payment',),
            ' u18': ('persona.birthday',),
            ' u16': ('persona.birthday',),
            ' u14': ('persona.birthday',),
            ' checked in': ('reg.checkin',),
            'total involved': ('part{part}.status',),
            'instructors': ('course_instructor{track}.id',),
            'all instructors': ('course{track}.id',
                                'course_instructor{track}.id',),
        }
        for name, track_regs in regs_in_choice_x.items():
            query_additional_fields[name] = ('track{track}.course_id',)

        def get_query(category: str, part_id: int, track_id: int = None
                      ) -> Optional[Query]:
            if category in registration_query_filters:
                q = copy.deepcopy(base_registration_query)
                filters = registration_query_filters
            elif category in course_query_filters:
                q = copy.deepcopy(base_course_query)
                filters = course_query_filters
            else:
                return None
            e = rs.ambience['event']
            p = e['parts'][part_id]
            t = e['tracks'][track_id] if track_id else None
            for c in filters[category](e, p, t):
                q.constraints.append(c)
            if category in query_additional_fields:
                for f in query_additional_fields[category]:
                    q.fields_of_interest.append(f.format(track=track_id,
                                                         part=part_id))
            return q

        def get_query_page(category: str) -> Optional[str]:
            if category in registration_query_filters:
                return "event/registration_query"
            elif category in course_query_filters:
                return "event/course_query"
            return None

        return self.render(rs, "stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_track_statistics': per_track_statistics,
            'get_query': get_query, 'get_query_page': get_query_page})

    @access("event")
    @event_guard()
    def course_assignment_checks(self, rs: RequestState, event_id: int
                                 ) -> Response:
        """Provide some consistency checks for course assignment."""
        event = rs.ambience['event']
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        stati = const.RegistrationPartStati

        # Helper for calculation of assign_counts
        course_participant_lists = {
            course_id: {
                track_id: [
                    reg for reg in registrations.values()
                    if (reg['tracks'][track_id]['course_id'] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             == stati.participant))]
                for track_id, track in tracks.items()
            }
            for course_id in course_ids
        }
        # Get number of attendees per course
        # assign_counts has the structure:
        # {course_id: {track_id: (num_participants, num_instructors)}}
        assign_counts = {
            course_id: {
                track_id: (
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            != course_id)),
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            == course_id))
                )
                for track_id, course_track_p_data in course_p_data.items()
            }
            for course_id, course_p_data in course_participant_lists.items()
        }

        # Tests for problematic courses
        course_tests = {
            'cancelled_with_p': lambda c, tid: (
                tid not in c['active_segments']
                and (assign_counts[c['id']][tid][0]
                     + assign_counts[c['id']][tid][1]) > 0),
            'many_p': lambda c, tid: (
                tid in c['active_segments']
                and c['max_size'] is not None
                and assign_counts[c['id']][tid][0] > c['max_size']),
            'few_p': lambda c, tid: (
                tid in c['active_segments']
                and c['min_size']
                and assign_counts[c['id']][tid][0] < c['min_size']),
            'no_instructor': lambda c, tid: (
                tid in c['active_segments']
                and assign_counts[c['id']][tid][1] <= 0),
        }

        # Calculate problematic course lists
        # course_problems will have the structure {key: [(reg_id, [track_id])]}
        max_course_no_len = max((len(c['nr']) for c in courses.values()),
                                default=0)
        course_problems = {}
        for key, test in course_tests.items():
            problems = []
            for course_id, course in courses.items():
                problem_tracks = [
                    track_id
                    for track_id in event['tracks']
                    if test(course, track_id)]
                if problem_tracks:
                    problems.append((course_id, problem_tracks))
            course_problems[key] = xsorted(
                problems, key=lambda problem:
                    courses[problem[0]]['nr'].rjust(max_course_no_len, '\0'))

        # Tests for registrations with problematic assignments
        reg_tests = {
            'no_course': lambda r, p, t: (
                p['status'] == stati.participant
                and not t['course_id']),
            'instructor_wrong_course': lambda r, p, t: (
                p['status'] == stati.participant
                and t['course_instructor']
                and t['track_id'] in
                    courses[t['course_instructor']]['active_segments']
                and t['course_id'] != t['course_instructor']),
            'unchosen': lambda r, p, t: (
                p['status'] == stati.participant
                and t['course_id']
                and t['course_id'] != t['course_instructor']
                and (t['course_id'] not in
                     t['choices']
                     [:event['tracks'][t['track_id']]['num_choices']])),
        }

        # Calculate problematic registrations
        # reg_problems will have the structure {key: [(reg_id, [track_id])]}
        reg_problems = {}
        for key, test in reg_tests.items():
            problems = []
            for reg_id, reg in registrations.items():
                problem_tracks = [
                    track_id
                    for part_id, part in event['parts'].items()
                    for track_id in part['tracks']
                    if test(reg, reg['parts'][part_id],
                            reg['tracks'][track_id])]
                if problem_tracks:
                    problems.append((reg_id, problem_tracks))
            reg_problems[key] = xsorted(
                problems, key=lambda problem:
                    EntitySorter.persona(
                        personas[registrations[problem[0]]['persona_id']]))

        return self.render(rs, "course_assignment_checks", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'course_problems': course_problems,
            'reg_problems': reg_problems})

    @access("event")
    @event_guard()
    @REQUESTdata("course_id", "track_id", "position", "ids", "include_active")
    def course_choices_form(
            self, rs: RequestState, event_id: int, course_id: Optional[vtypes.ID],
            track_id: Optional[vtypes.ID],
            position: Optional[InfiniteEnum[CourseFilterPositions]],
            ids: Optional[vtypes.IntCSVList], include_active: Optional[bool]
            ) -> Response:
        """Provide an overview of course choices.

        This allows flexible filtering of the displayed registrations.
        """
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
        stati = const.RegistrationPartStati

        if rs.has_validation_errors():
            registration_ids = all_reg_ids
            registrations = all_regs
            personas = self.coreproxy.get_personas(
                rs, tuple(r['persona_id'] for r in registrations.values()))
        else:
            if include_active:
                include_states = tuple(
                    status for status in const.RegistrationPartStati if
                    status.is_involved())
            else:
                include_states = (const.RegistrationPartStati.participant,)
            registration_ids = self.eventproxy.registrations_by_course(
                rs, event_id, course_id, track_id, position, ids,
                include_states)
            registrations = self.eventproxy.get_registrations(
                rs, registration_ids.keys())
            personas = self.coreproxy.get_personas(
                rs, registration_ids.values())

        course_infos = {}
        reg_part = lambda registration, track_id: \
            registration['parts'][tracks[track_id]['part_id']]
        for course_id, course in courses.items():  # pylint: disable=redefined-argument-from-local
            for track_id in tracks:  # pylint: disable=redefined-argument-from-local
                assigned = sum(
                    1 for reg in all_regs.values()
                    if reg_part(reg, track_id)['status'] == stati.participant
                    and reg['tracks'][track_id]['course_id'] == course_id and
                    reg['tracks'][track_id]['course_instructor'] != course_id)
                all_instructors = sum(
                    1 for reg in all_regs.values()
                    if
                    reg['tracks'][track_id]['course_instructor'] == course_id)
                assigned_instructors = sum(
                    1 for reg in all_regs.values()
                    if reg_part(reg, track_id)['status'] == stati.participant
                    and reg['tracks'][track_id]['course_id'] == course_id
                    and reg['tracks'][track_id][
                        'course_instructor'] == course_id)
                course_infos[(course_id, track_id)] = {
                    'assigned': assigned,
                    'all_instructors': all_instructors,
                    'assigned_instructors': assigned_instructors,
                    'is_happening': track_id in course['segments'],
                }
        corresponding_query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"] + [
                "course{0}.id".format(track_id)
                for track_id in tracks],
            (("reg.id", QueryOperators.oneof, registration_ids.keys()),),
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        filter_entries = [
            (CourseFilterPositions.anywhere.value,
             rs.gettext("somehow know")),
            (CourseFilterPositions.assigned.value,
             rs.gettext("participate in")),
            (CourseFilterPositions.instructor.value,
             rs.gettext("offer")),
            (CourseFilterPositions.any_choice.value,
             rs.gettext("chose"))
        ]
        filter_entries.extend(
            (i, rs.gettext("have as {}. choice").format(i + 1))
            for i in range(max(t['num_choices'] for t in tracks.values())))
        action_entries = [
            (i, rs.gettext("into their {}. choice").format(i + 1))
            for i in range(max(t['num_choices'] for t in tracks.values()))]
        action_entries.extend((
            (CourseChoiceToolActions.assign_fixed.value,
             rs.gettext("in the course …")),
            (CourseChoiceToolActions.assign_auto.value,
             rs.gettext("automatically"))))
        return self.render(rs, "course_choices", {
            'courses': courses, 'personas': personas,
            'registrations': OrderedDict(
                xsorted(registrations.items(),
                        key=lambda reg: EntitySorter.persona(
                           personas[reg[1]['persona_id']]))),
            'course_infos': course_infos,
            'corresponding_query': corresponding_query,
            'filter_entries': filter_entries,
            'action_entries': action_entries})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("course_id", "track_id", "position", "ids", "include_active",
                 "registration_ids", "assign_track_ids", "assign_action",
                 "assign_course_id")
    def course_choices(self, rs: RequestState, event_id: int,
                       course_id: Optional[vtypes.ID], track_id: Optional[vtypes.ID],
                       position: Optional[InfiniteEnum[CourseFilterPositions]],
                       ids: Optional[vtypes.IntCSVList],
                       include_active: Optional[bool],
                       registration_ids: Collection[int],
                       assign_track_ids: Collection[int],
                       assign_action: InfiniteEnum[CourseChoiceToolActions],
                       assign_course_id: Optional[vtypes.ID]) -> Response:
        """Manipulate course choices.

        The first four parameters (course_id, track_id, position, ids) are the
        filter parameters for the course_choices_form used for displaying
        an equally filtered form on validation errors or after successful
        submit.

        Allow assignment of multiple people in multiple tracks to one of
        their choices or a specific course.
        """
        if rs.has_validation_errors():
            return self.course_choices_form(rs, event_id)  # type: ignore
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        courses = None
        if assign_action.enum == CourseChoiceToolActions.assign_auto:
            course_ids = self.eventproxy.list_courses(rs, event_id)
            courses = self.eventproxy.get_courses(rs, course_ids)

        num_committed = 0
        for registration_id in registration_ids:
            persona = personas[registrations[registration_id]['persona_id']]
            tmp: CdEDBObject = {
                'id': registration_id,
                'tracks': {}
            }
            for atrack_id in assign_track_ids:
                reg_part = registrations[registration_id]['parts'][
                    tracks[atrack_id]['part_id']]
                reg_track = registrations[registration_id]['tracks'][atrack_id]
                if (reg_part['status']
                        != const.RegistrationPartStati.participant):
                    continue
                if assign_action.enum == CourseChoiceToolActions.specific_rank:
                    if assign_action.int >= len(reg_track['choices']):
                        rs.notify("warning",
                                  (n_("%(given_names)s %(family_name)s has no "
                                      "%(rank)i. choice in %(track_name)s.")
                                   if len(tracks) > 1
                                   else n_("%(given_names)s %(family_name)s "
                                           "has no %(rank)i. choice.")),
                                  {'given_names': persona['given_names'],
                                   'family_name': persona['family_name'],
                                   'rank': assign_action.int + 1,
                                   'track_name': tracks[atrack_id]['title']})
                        continue
                    choice = reg_track['choices'][assign_action.int]
                    tmp['tracks'][atrack_id] = {'course_id': choice}
                elif assign_action.enum == CourseChoiceToolActions.assign_fixed:
                    tmp['tracks'][atrack_id] = {'course_id': assign_course_id}
                elif assign_action.enum == CourseChoiceToolActions.assign_auto:
                    cid = reg_track['course_id']
                    assert courses is not None
                    if cid and atrack_id in courses[cid]['active_segments']:
                        # Do not modify a valid assignment
                        continue
                    instructor = reg_track['course_instructor']
                    if (instructor
                            and atrack_id in courses[instructor]
                            ['active_segments']):
                        # Let instructors instruct
                        tmp['tracks'][atrack_id] = {'course_id': instructor}
                        continue
                    for choice in (
                            reg_track['choices'][
                            :tracks[atrack_id]['num_choices']]):
                        if atrack_id in courses[choice]['active_segments']:
                            # Assign first possible choice
                            tmp['tracks'][atrack_id] = {'course_id': choice}
                            break
                    else:
                        rs.notify("warning",
                                  (n_("No choice available for %(given_names)s "
                                      "%(family_name)s in %(track_name)s.")
                                   if len(tracks) > 1
                                   else n_("No choice available for "
                                           "%(given_names)s %(family_name)s.")),
                                  {'given_names': persona['given_names'],
                                   'family_name': persona['family_name'],
                                   'track_name': tracks[atrack_id]['title']})
            if tmp['tracks']:
                res = self.eventproxy.set_registration(rs, tmp)
                if res:
                    num_committed += 1
                else:
                    rs.notify("warning",
                              n_("Error committing changes for %(given_names)s "
                                 "%(family_name)s."),
                              {'given_names': persona['given_names'],
                               'family_name': persona['family_name']})
        rs.notify("success" if num_committed > 0 else "warning",
                  n_("Course assignment for %(num_committed)s of %(num_total)s "
                     "registrations committed."),
                  {'num_total': len(registration_ids),
                   'num_committed': num_committed})
        return self.redirect(
            rs, "event/course_choices_form",
            {'course_id': course_id, 'track_id': track_id,
             'position': position.value if position is not None else None,
             'ids': ",".join(str(i) for i in ids),
             'include_active': include_active})

    @access("event")
    @event_guard()
    @REQUESTdata("include_active")
    def course_stats(self, rs: RequestState, event_id: int, include_active: bool
                     ) -> Response:
        """List courses.

        Provide an overview of the number of choices and assignments for
        all courses.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/show_event')
        if include_active:
            include_states = tuple(
                status for status in const.RegistrationPartStati
                if status.is_involved())
        else:
            include_states = (const.RegistrationPartStati.participant,)

        event = rs.ambience['event']
        tracks = event['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        choice_counts = {
            course_id: {
                (track_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['tracks'][track_id]['choices']) > i
                        and reg['tracks'][track_id]['choices'][i] == course_id
                        and (reg['parts'][tracks[track_id]['part_id']]['status']
                             in include_states)))
                for track_id, track in tracks.items()
                for i in range(track['num_choices'])
            }
            for course_id in course_ids
        }
        # Helper for calculation of assign_counts
        course_participant_lists = {
            course_id: {
                track_id: [
                    reg for reg in registrations.values()
                    if (reg['tracks'][track_id]['course_id'] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             in include_states))]
                for track_id, track in tracks.items()
            }
            for course_id in course_ids
        }
        # Tuple of (number of assigned participants, number of instructors) for
        # each course in each track
        assign_counts = {
            course_id: {
                track_id: (
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                                 != course_id)),
                    sum(1 for reg in course_track_p_data
                        if (reg['tracks'][track_id]['course_instructor']
                            == course_id))
                )
                for track_id, course_track_p_data in course_p_data.items()
            }
            for course_id, course_p_data in course_participant_lists.items()
        }
        return self.render(rs, "course_stats", {
            'courses': courses, 'choice_counts': choice_counts,
            'assign_counts': assign_counts, 'include_active': include_active})

    @access("event")
    @event_guard(check_offline=True)
    def batch_fees_form(self, rs: RequestState, event_id: int,
                        data: Collection[CdEDBObject] = None,
                        csvfields: Collection[str] = None,
                        saldo: decimal.Decimal = None) -> Response:
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or []
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['persona_id'] = csv_position.pop('id', -1)
        return self.render(rs, "batch_fees",
                           {'data': data, 'csvfields': csv_position,
                            'saldo': saldo})

    def examine_fee(self, rs: RequestState, datum: CdEDBObject,
                    expected_fees: Dict[int, decimal.Decimal],
                    full_payment: bool = True) -> CdEDBObject:
        """Check one line specifying a paid fee.

        We test for fitness of the data itself.

        :param full_payment: If True, only write the payment date if the fee
            was paid in full.
        :returns: The processed input datum.
        """
        event = rs.ambience['event']
        warnings = []
        infos = []
        # Allow an amount of zero to allow non-modification of amount_paid.
        amount: Optional[decimal.Decimal]
        amount, problems = validate_check(vtypes.NonNegativeDecimal,
            datum['raw']['amount'].strip(), argname="amount")
        persona_id, p = validate_check(vtypes.CdedbID,
            datum['raw']['id'].strip(), argname="persona_id")
        problems.extend(p)
        family_name, p = validate_check(str,
            datum['raw']['family_name'], argname="family_name")
        problems.extend(p)
        given_names, p = validate_check(str,
            datum['raw']['given_names'], argname="given_names")
        problems.extend(p)
        date, p = validate_check(datetime.date,
            datum['raw']['date'].strip(), argname="date")
        problems.extend(p)

        registration_id = None
        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append(('persona_id',
                                 ValueError(
                                     n_("No Member with ID %(p_id)s found."),
                                     {"p_id": persona_id})))
            else:
                registration_ids = self.eventproxy.list_registrations(
                    rs, event['id'], persona_id).keys()
                if registration_ids:
                    registration_id = unwrap(registration_ids)
                    registration = self.eventproxy.get_registration(
                        rs, registration_id)
                    amount = amount or decimal.Decimal(0)
                    amount_paid = registration['amount_paid']
                    total = amount + amount_paid
                    fee = expected_fees[registration_id]
                    if total < fee:
                        error = ('amount', ValueError(n_("Not enough money.")))
                        if full_payment:
                            warnings.append(error)
                            date = None
                        else:
                            infos.append(error)
                    elif total > fee:
                        warnings.append(('amount',
                                         ValueError(n_("Too much money."))))
                else:
                    problems.append(('persona_id',
                                     ValueError(n_("No registration found."))))

                if family_name is not None and not re.search(
                    diacritic_patterns(re.escape(family_name)),
                    persona['family_name'],
                    flags=re.IGNORECASE
                ):
                    warnings.append(('family_name', ValueError(
                        n_("Family name doesn’t match."))))

                if given_names is not None and not re.search(
                    diacritic_patterns(re.escape(given_names)),
                    persona['given_names'],
                    flags=re.IGNORECASE
                ):
                    warnings.append(('given_names', ValueError(
                        n_("Given names don’t match."))))
        datum.update({
            'persona_id': persona_id,
            'registration_id': registration_id,
            'date': date,
            'amount': amount,
            'warnings': warnings,
            'problems': problems,
            'infos': infos,
        })
        return datum

    def book_fees(self, rs: RequestState, data: Collection[CdEDBObject],
                  send_notifications: bool = False
                  ) -> Tuple[bool, Optional[int]]:
        """Book all paid fees.

        :returns: Success information and

          * for positive outcome the number of recorded transfers
          * for negative outcome the line where an exception was triggered
            or None if it was a DB serialization error
        """
        index = 0
        try:
            with Atomizer(rs):
                count = 0
                all_reg_ids = {datum['registration_id'] for datum in data}
                all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
                for index, datum in enumerate(data):
                    reg_id = datum['registration_id']
                    update = {
                        'id': reg_id,
                        'payment': datum['date'],
                        'amount_paid': all_regs[reg_id]['amount_paid']
                                       + datum['amount'],
                    }
                    count += self.eventproxy.set_registration(rs, update)
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None
        except Exception:
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
        if send_notifications:
            persona_ids = tuple(e['persona_id'] for e in data)
            personas = self.coreproxy.get_personas(rs, persona_ids)
            subject = "Überweisung für {} eingetroffen".format(
                rs.ambience['event']['title'])
            for persona in personas.values():
                headers: Dict[str, Union[str, Collection[str]]] = {
                    'To': (persona['username'],),
                    'Subject': subject,
                }
                if rs.ambience['event']['orga_address']:
                    headers['Reply-To'] = rs.ambience['event']['orga_address']
                self.do_mail(rs, "transfer_received", headers,
                             {'persona': persona})
        return True, count

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("fee_data_file")
    @REQUESTdata("force", "fee_data", "checksum", "send_notifications", "full_payment")
    def batch_fees(self, rs: RequestState, event_id: int, force: bool,
                   fee_data: Optional[str],
                   fee_data_file: Optional[werkzeug.datastructures.FileStorage],
                   checksum: Optional[str], send_notifications: bool,
                   full_payment: bool) -> Response:
        """Allow orgas to add lots paid of participant fee at once."""
        fee_data_file = check_optional(
            rs, vtypes.CSVFile, fee_data_file, "fee_data_file")
        if rs.has_validation_errors():
            return self.batch_fees_form(rs, event_id)

        if fee_data_file and fee_data:
            rs.notify("warning", n_("Only one input method allowed."))
            return self.batch_fees_form(rs, event_id)
        elif fee_data_file:
            rs.values["fee_data"] = fee_data_file
            fee_data = fee_data_file
            fee_data_lines = fee_data_file.splitlines()
        elif fee_data:
            fee_data_lines = fee_data.splitlines()
        else:
            rs.notify("error", n_("No input provided."))
            return self.batch_fees_form(rs, event_id)

        reg_ids = self.eventproxy.list_registrations(rs, event_id=event_id)
        expected_fees = self.eventproxy.calculate_fees(rs, reg_ids)

        fields = ('amount', 'id', 'family_name', 'given_names', 'date')
        reader = csv.DictReader(
            fee_data_lines, fieldnames=fields, dialect=CustomCSVDialect())
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset: CdEDBObject = {'raw': raw_entry}
            lineno += 1
            dataset['lineno'] = lineno
            data.append(self.examine_fee(
                rs, dataset, expected_fees, full_payment))
        if lineno != len(fee_data_lines):
            rs.append_validation_error(
                ("fee_data", ValueError(n_("Lines didn’t match up."))))
        open_issues = any(e['problems'] for e in data)
        saldo: decimal.Decimal = sum(
            (e['amount'] for e in data if e['amount']), decimal.Decimal("0.00"))
        if not force:
            open_issues = open_issues or any(e['warnings'] for e in data)
        if rs.has_validation_errors() or not data or open_issues:
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

        current_checksum = get_hash(fee_data.encode())
        if checksum != current_checksum:
            rs.values['checksum'] = current_checksum
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields, saldo=saldo)

        # Here validation is finished
        success, num = self.book_fees(rs, data, send_notifications)
        if success:
            rs.notify("success", n_("Committed %(num)s fees."), {'num': num})
            return self.redirect(rs, "event/show_event")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line {num}."),
                          {'num': num + 1})
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

    @access("event")
    @event_guard()
    def downloads(self, rs: RequestState, event_id: int) -> Response:
        """Offer documents like nametags for download."""
        return self.render(rs, "downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_nametags(self, rs: RequestState, event_id: int,
                          runs: vtypes.SingleDigitInt) -> Response:
        """Create nametags.

        You probably want to edit the provided tex file.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event']['begin'])
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        tex = self.fill_template(rs, "tex", "nametags", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'courses': courses})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_nametags.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "aka-logo.png")
            shutil.copy(src, work_dir / "orga-logo.png")
            shutil.copy(src, work_dir / "minor-pictogram.png")
            shutil.copy(src, work_dir / "multicourse-logo.png")
            for course_id in courses:
                shutil.copy(src, work_dir / "logo-{}.png".format(course_id))
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_nametags.tex".format(rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_course_puzzle(self, rs: RequestState, event_id: int,
                               runs: vtypes.SingleDigitInt) -> Response:
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        event = rs.ambience['event']
        tracks = event['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        counts = {
            course_id: {
                (track_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['tracks'][track_id]['choices']) > i
                        and reg['tracks'][track_id]['choices'][i] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             == const.RegistrationPartStati.participant)))
                for track_id, track in tracks.items() for i in
                range(track['num_choices'])
            }
            for course_id in course_ids
        }
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        tex = self.fill_template(rs, "tex", "course_puzzle", {
            'courses': courses, 'counts': counts,
            'tracks_sorted': tracks_sorted, 'registrations': registrations,
            'personas': personas})
        file = self.serve_latex_document(
            rs, tex,
            "{}_course_puzzle".format(rs.ambience['event']['shortname']), runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_lodgement_puzzle(self, rs: RequestState, event_id: int,
                                  runs: vtypes.SingleDigitInt) -> Response:
        """Aggregate lodgement information.

        This can be printed and cut to help with distribution of participants.
        This make use of the lodge_field and the camping_mat_field.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        event = rs.ambience['event']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                event['begin'])
        key = (lambda reg_id:
               personas[registrations[reg_id]['persona_id']]['birthday'])
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in xsorted(registrations,
                                                                  key=key))
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)

        reverse_wish = {}
        if event['lodge_field']:
            for reg_id, reg in registrations.items():
                rwish = set()
                persona = personas[reg['persona_id']]
                checks = {
                    diacritic_patterns("{} {}".format(
                        given_name, persona['family_name']))
                    for given_name in persona['given_names'].split()}
                checks.add(diacritic_patterns("{} {}".format(
                    persona['display_name'], persona['family_name'])))
                for oid, other in registrations.items():
                    owish = other['fields'].get(
                        event['fields'][event['lodge_field']]['field_name'])
                    if not owish:
                        continue
                    if any(re.search(acheck, owish, flags=re.IGNORECASE)
                                     for acheck in checks):
                        rwish.add(oid)
                reverse_wish[reg_id] = ", ".join(
                    "{} {}".format(
                        personas[registrations[id]['persona_id']]['given_names'],
                        personas[registrations[id]['persona_id']]['family_name'])
                    for id in rwish)

        tex = self.fill_template(rs, "tex", "lodgement_puzzle", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'reverse_wish': reverse_wish})
        file = self.serve_latex_document(rs, tex, "{}_lodgement_puzzle".format(
            rs.ambience['event']['shortname']), runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_course_lists(self, rs: RequestState, event_id: int,
                              runs: vtypes.SingleDigitInt) -> Response:
        """Create lists to post to course rooms."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        tracks = rs.ambience['event']['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        for p_id, p in personas.items():
            p['age'] = determine_age_class(
                p['birthday'], rs.ambience['event']['begin'])
        attendees = self.calculate_groups(
            courses, rs.ambience['event'], registrations, key="course_id",
            personas=personas)
        instructors = {}
        # Look for the field name of the course_room_field.
        cr_field_id = rs.ambience['event']['course_room_field']
        cr_field = rs.ambience['event']['fields'].get(cr_field_id, {})
        cr_field_name = cr_field.get('field_name')
        for c_id, course in courses.items():
            for t_id in course['active_segments']:
                instructors[(c_id, t_id)] = [
                    r_id
                    for r_id in attendees[(c_id, t_id)]
                    if (registrations[r_id]['tracks'][t_id]['course_instructor']
                        == c_id)
                ]
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        tex = self.fill_template(rs, "tex", "course_lists", {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'instructors': instructors, 'course_room_field': cr_field_name,
            'tracks_sorted': tracks_sorted, })
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_course_lists.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "event-logo.png")
            for course_id in courses:
                dest = work_dir / "course-logo-{}.png".format(course_id)
                path = self.conf["STORAGE_DIR"] / "course_logo" / str(course_id)
                if path.exists():
                    shutil.copy(path, dest)
                else:
                    shutil.copy(src, dest)
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_course_lists.tex".format(rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs")
    def download_lodgement_lists(self, rs: RequestState, event_id: int,
                                 runs: vtypes.SingleDigitInt) -> Response:
        """Create lists to post to lodgements."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id",
            personas=personas)
        tex = self.fill_template(rs, "tex", "lodgement_lists", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            filename = "{}_lodgement_lists.tex".format(
                rs.ambience['event']['shortname'])
            with open(work_dir / filename, 'w') as f:
                f.write(tex)
            src = self.conf["REPOSITORY_PATH"] / "misc/blank.png"
            shutil.copy(src, work_dir / "aka-logo.png")
            file = self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "{}_lodgement_lists.tex".format(
                    rs.ambience['event']['shortname']),
                runs)
            if file:
                return file
            else:
                rs.notify("info", n_("Empty PDF."))
                return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    @REQUESTdata("runs", "landscape", "orgas_only", "part_ids")
    def download_participant_list(self, rs: RequestState, event_id: int,
                                  runs: vtypes.SingleDigitInt, landscape: bool,
                                  orgas_only: bool,
                                  part_ids: Collection[vtypes.ID]) -> Response:
        """Create list to send to all participants."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        data = self._get_participant_list_data(rs, event_id, part_ids)
        if runs and not data['registrations']:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")
        data['orientation'] = "landscape" if landscape else "portrait"
        data['orgas_only'] = orgas_only
        tex = self.fill_template(rs, "tex", "participant_list", data)
        file = self.serve_latex_document(
            rs, tex, "{}_participant_list".format(
                rs.ambience['event']['shortname']),
            runs)
        if file:
            return file
        else:
            rs.notify("info", n_("Empty PDF."))
            return self.redirect(rs, "event/downloads")

    @access("event")
    @event_guard()
    def download_dokuteam_courselist(self, rs: RequestState, event_id: int) -> Response:
        """A pipe-seperated courselist for the dokuteam aca-generator script."""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        if not course_ids:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        courses = self.eventproxy.get_courses(rs, course_ids)
        data = self.fill_template(
            rs, "other", "dokuteam_courselist", {'courses': courses})
        return self.send_file(
            rs, data=data, inline=False,
            filename=f"{rs.ambience['event']['shortname']}_dokuteam_courselist.txt")

    @access("event")
    @event_guard()
    def download_dokuteam_participant_list(self, rs: RequestState,
                                           event_id: int) -> Response:
        """Create participant list per track for dokuteam."""
        event = self.eventproxy.get_event(rs, event_id)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        spec = self.make_registration_query_spec(event)

        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()

            # create one list per track
            for part in rs.ambience["event"]["parts"].values():
                for track_id, track in part["tracks"].items():
                    fields_of_interest = ["persona.given_names", "persona.family_name",
                                          f"track{track_id}.course_id"]
                    constrains = [(f"track{track_id}.course_id",
                                   QueryOperators.nonempty, None)]
                    order = [("persona.given_names", True)]
                    query = Query("qview_registration", spec, fields_of_interest,
                                  constrains, order)
                    query_res = self.eventproxy.submit_general_query(rs, query, event_id)
                    course_key = f"track{track_id}.course_id"
                    # we have to replace the course id with the course number
                    result = tuple(
                        {
                            k if k != course_key else 'course':
                                v if k != course_key else courses[v]['nr']
                            for k, v in entry.items()
                        }
                        for entry in query_res
                    )
                    data = self.fill_template(
                        rs, "other", "dokuteam_participant_list", {'result': result})

                    # save the result in one file per track
                    filename = f"{asciificator(track['shortname'])}.csv"
                    file = pathlib.Path(work_dir, filename)
                    file.write_text(data)

            # create a zip archive of all lists
            zipname = f"{rs.ambience['event']['shortname']}_dokuteam_participant_list"
            zippath = shutil.make_archive(str(pathlib.Path(tmp_dir, zipname)), 'zip',
                                          base_dir=work_dir, root_dir=tmp_dir)

            return self.send_file(rs, path=zippath, inline=False,
                                  filename=f"{zipname}.zip")

    @access("event")
    @event_guard()
    def download_csv_courses(self, rs: RequestState, event_id: int) -> Response:
        """Create CSV file with all courses"""
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)

        spec = self.make_course_query_spec(rs.ambience['event'])
        choices, _ = self.make_course_query_aux(
            rs, rs.ambience['event'], courses, fixed_gettext=True)
        fields_of_interest = list(spec.keys())
        query = Query('qview_event_course', spec, fields_of_interest, [], [])
        result = self.eventproxy.submit_general_query(rs, query, event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_courses")

    @access("event")
    @event_guard()
    def download_csv_lodgements(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Create CSV file with all courses"""
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)

        spec = self.make_lodgement_query_spec(rs.ambience['event'])
        choices, _ = self.make_lodgement_query_aux(
            rs, rs.ambience['event'], lodgements, groups, fixed_gettext=True)
        fields_of_interest = list(spec.keys())
        query = Query('qview_event_lodgement', spec, fields_of_interest, [], [])
        result = self.eventproxy.submit_general_query(rs, query, event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_lodgements")

    @access("event")
    @event_guard()
    def download_csv_registrations(self, rs: RequestState, event_id: int
                                   ) -> Response:
        """Create CSV file with all registrations"""
        # Get data
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)

        spec = self.make_registration_query_spec(rs.ambience['event'])
        fields_of_interest = list(spec.keys())
        choices, _ = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements, lodgement_groups,
            fixed_gettext=True)
        query = Query('qview_registration', spec, fields_of_interest, [], [])
        result = self.eventproxy.submit_general_query(
            rs, query, event_id=event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        return self.send_query_download(
            rs, result, fields_of_interest, "csv", substitutions=choices,
            filename=f"{rs.ambience['event']['shortname']}_registrations")

    @access("event", modi={"GET"})
    @event_guard()
    @REQUESTdata("agree_unlocked_download")
    def download_export(self, rs: RequestState, event_id: int,
                        agree_unlocked_download: Optional[bool]) -> Response:
        """Retrieve all data for this event to initialize an offline
        instance."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")

        if not (agree_unlocked_download
                or rs.ambience['event']['offline_lock']):
            rs.notify("info", n_("Please confirm to download a full export of "
                                 "an unlocked event."))
            return self.redirect(rs, "event/show_event")
        data = self.eventproxy.export_event(rs, event_id)
        if not data:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/show_event")
        json = json_serialize(data)
        return self.send_file(
            rs, data=json, inline=False,
            filename=f"{rs.ambience['event']['shortname']}_export_event.json")

    @access("event")
    @event_guard()
    def download_partial_export(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Retrieve data for third-party applications."""
        data = self.eventproxy.partial_export_event(rs, event_id)
        if not data:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        json = json_serialize(data)
        return self.send_file(
            rs, data=json, inline=False,
            filename="{}_partial_export_event.json".format(
                rs.ambience['event']['shortname']))

    @access("droid_quick_partial_export")
    def download_quick_partial_export(self, rs: RequestState) -> Response:
        """Retrieve data for third-party applications in offline mode.

        This is a zero-config variant of download_partial_export.
        """
        ret = {
            'message': "",
            'export': {},
        }
        if not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
            ret['message'] = "Not in offline mode."
            return self.send_json(rs, ret)
        events = self.eventproxy.list_events(rs)
        if len(events) != 1:
            ret['message'] = "Exactly one event must exist."
            return self.send_json(rs, ret)
        event_id = unwrap(events.keys())
        ret['export'] = self.eventproxy.partial_export_event(rs, event_id)
        ret['message'] = "success"
        return self.send_json(rs, ret)

    @access("event")
    @event_guard()
    def partial_import_form(self, rs: RequestState, event_id: int) -> Response:
        """First step of partial import process: Render form to upload file"""
        return self.render(rs, "partial_import")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTfile("json_file")
    @REQUESTdata("partial_import_data", "token")
    def partial_import(self, rs: RequestState, event_id: int,
                       json_file: Optional[werkzeug.datastructures.FileStorage],
                       partial_import_data: Optional[str], token: Optional[str]
                       ) -> Response:
        """Further steps of partial import process

        This takes the changes and generates a transaction token. If the new
        token agrees with the submitted token, the change were successfully
        applied, otherwise a diff-view of the changes is displayed.

        In the first iteration the data is extracted from a file upload and
        in further iterations it is embedded in the page.
        """
        if partial_import_data:
            data = check(rs, vtypes.SerializedPartialEvent,
                         json.loads(partial_import_data))
        else:
            data = check(rs, vtypes.SerializedPartialEventUpload, json_file)
        if rs.has_validation_errors():
            return self.partial_import_form(rs, event_id)
        assert data is not None
        if event_id != data['id']:
            rs.notify("error", n_("Data from wrong event."))
            return self.partial_import_form(rs, event_id)

        # First gather infos for comparison
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(
            rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(
            rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(
            rs, lodgement_group_ids)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        persona_ids = (
            ({e['persona_id'] for e in registrations.values()}
             | {e.get('persona_id')
                for e in data.get('registrations', {}).values() if e})
            - {None})
        personas = self.coreproxy.get_personas(rs, persona_ids)

        # Second invoke partial import
        try:
            new_token, delta = self.eventproxy.partial_import_event(
                rs, data, dryrun=(not bool(token)), token=token)
        except PartialImportError:
            rs.notify("warning",
                      n_("The data changed, please review the difference."))
            token = None
            new_token, delta = self.eventproxy.partial_import_event(
                rs, data, dryrun=True)

        # Third check if we were successful
        if token == new_token:
            rs.notify("success", n_("Changes applied."))
            return self.redirect(rs, "event/show_event")

        # Fourth prepare
        rs.values['token'] = new_token
        rs.values['partial_import_data'] = json_serialize(data)
        for course in courses.values():
            course['segments'] = {
                id: id in course['active_segments']
                for id in course['segments']
            }

        # Fifth prepare summary
        def flatten_recursive_delta(data: Mapping[Any, Any],
                                    old: Mapping[Any, Any],
                                    prefix: str = "") -> CdEDBObject:
            ret = {}
            for key, val in data.items():
                if isinstance(val, collections.abc.Mapping):
                    tmp = flatten_recursive_delta(
                        val, old.get(key, {}), f"{prefix}{key}.")
                    ret.update(tmp)
                else:
                    ret[f"{prefix}{key}"] = (old.get(key, None), val)
            return ret

        summary: CdEDBObject = {
            'changed_registrations': {
                anid: flatten_recursive_delta(val, registrations[anid])
                for anid, val in delta.get('registrations', {}).items()
                if anid > 0 and val
            },
            'new_registration_ids': tuple(xsorted(
                anid for anid in delta.get('registrations', {})
                if anid < 0)),
            'deleted_registration_ids': tuple(xsorted(
                anid for anid, val in delta.get('registrations', {}).items()
                if val is None)),
            'real_deleted_registration_ids': tuple(xsorted(
                anid for anid, val in delta.get('registrations', {}).items()
                if val is None and registrations.get(anid))),
            'changed_courses': {
                anid: flatten_recursive_delta(val, courses[anid])
                for anid, val in delta.get('courses', {}).items()
                if anid > 0 and val
            },
            'new_course_ids': tuple(xsorted(
                anid for anid in delta.get('courses', {}) if anid < 0)),
            'deleted_course_ids': tuple(xsorted(
                anid for anid, val in delta.get('courses', {}).items()
                if val is None)),
            'real_deleted_course_ids': tuple(xsorted(
                anid for anid, val in delta.get('courses', {}).items()
                if val is None and courses.get(anid))),
            'changed_lodgements': {
                anid: flatten_recursive_delta(val, lodgements[anid])
                for anid, val in delta.get('lodgements', {}).items()
                if anid > 0 and val
            },
            'new_lodgement_ids': tuple(xsorted(
                anid for anid in delta.get('lodgements', {}) if anid < 0)),
            'deleted_lodgement_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgements', {}).items()
                if val is None)),
            'real_deleted_lodgement_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgements', {}).items()
                if val is None and lodgements.get(anid))),

            'changed_lodgement_groups': {
                anid: flatten_recursive_delta(val, lodgement_groups[anid])
                for anid, val in delta.get('lodgement_groups', {}).items()
                if anid > 0 and val},
            'new_lodgement_group_ids': tuple(xsorted(
                anid for anid in delta.get('lodgement_groups', {})
                if anid < 0)),
            'real_deleted_lodgement_group_ids': tuple(xsorted(
                anid for anid, val in delta.get('lodgement_groups', {}).items()
                if val is None and lodgement_groups.get(anid))),
        }

        changed_registration_fields: Set[str] = set()
        for reg in summary['changed_registrations'].values():
            changed_registration_fields |= reg.keys()
        summary['changed_registration_fields'] = tuple(xsorted(
            changed_registration_fields))
        changed_course_fields: Set[str] = set()
        for course in summary['changed_courses'].values():
            changed_course_fields |= course.keys()
        summary['changed_course_fields'] = tuple(xsorted(
            changed_course_fields))
        changed_lodgement_fields: Set[str] = set()
        for lodgement in summary['changed_lodgements'].values():
            changed_lodgement_fields |= lodgement.keys()
        summary['changed_lodgement_fields'] = tuple(xsorted(
            changed_lodgement_fields))

        (reg_titles, reg_choices, course_titles, course_choices,
         lodgement_titles) = self._make_partial_import_diff_aux(
            rs, rs.ambience['event'], courses, lodgements)

        # Sixth look for double deletions/creations
        if (len(summary['deleted_registration_ids'])
                > len(summary['real_deleted_registration_ids'])):
            rs.notify('warning', n_("There were double registration deletions."
                                    " Did you already import this file?"))
        if len(summary['deleted_course_ids']) > len(summary['real_deleted_course_ids']):
            rs.notify('warning', n_("There were double course deletions."
                                    " Did you already import this file?"))
        if (len(summary['deleted_lodgement_ids'])
                > len(summary['real_deleted_lodgement_ids'])):
            rs.notify('warning', n_("There were double lodgement deletions."
                                    " Did you already import this file?"))
        all_current_data = self.eventproxy.partial_export_event(rs, data['id'])
        for course_id, course in delta.get('courses', {}).items():
            if course_id < 0:
                if any(current == course
                       for current in all_current_data['courses'].values()):
                    rs.notify('warning',
                              n_("There were hints at double course creations."
                                 " Did you already import this file?"))
                    break
        for lodgement_id, lodgement in delta.get('lodgements', {}).items():
            if lodgement_id < 0:
                if any(current == lodgement
                       for current in all_current_data['lodgements'].values()):
                    rs.notify('warning',
                              n_("There were hints at double lodgement creations."
                                 " Did you already import this file?"))
                    break

        # Seventh render diff
        template_data = {
            'delta': delta,
            'registrations': registrations,
            'lodgements': lodgements,
            'lodgement_groups': lodgement_groups,
            'courses': courses,
            'personas': personas,
            'summary': summary,
            'reg_titles': reg_titles,
            'reg_choices': reg_choices,
            'course_titles': course_titles,
            'course_choices': course_choices,
            'lodgement_titles': lodgement_titles,
        }
        return self.render(rs, "partial_import_check", template_data)

    # TODO: be more specific about the return types.
    @staticmethod
    def _make_partial_import_diff_aux(
            rs: RequestState, event: CdEDBObject, courses: CdEDBObjectMap,
            lodgements: CdEDBObjectMap
    ) -> Tuple[CdEDBObject, CdEDBObject, CdEDBObject, CdEDBObject, CdEDBObject]:
        """ Helper method, similar to make_registration_query_aux(), to
        generate human readable field names and values for the diff presentation
        of partial_import().

        This method does only generate titles and choice-dicts for the dynamic,
        event-specific fields (i.e. part- and track-specific and custom fields).
        Titles for all static fields are added in the template file."""
        reg_titles = {}
        reg_choices = {}
        course_titles = {}
        course_choices = {}
        lodgement_titles = {}

        # Prepare choices lists
        # TODO distinguish old and new course/lodgement titles
        # Heads up! There's a protected space (u+00A0) in the string below
        course_entries = {
            c["id"]: "{}. {}".format(c["nr"], c["shortname"])
            for c in courses.values()}
        lodgement_entries = {l["id"]: l["title"]
                             for l in lodgements.values()}
        reg_part_stati_entries =\
            dict(enum_entries_filter(const.RegistrationPartStati, rs.gettext))
        segment_stati_entries = {
            None: rs.gettext('not offered'),
            False: rs.gettext('cancelled'),
            True: rs.gettext('takes place'),
        }

        # Titles and choices for track-specific fields
        for track_id, track in event['tracks'].items():
            if len(event['tracks']) > 1:
                prefix = "{title}: ".format(title=track['shortname'])
            else:
                prefix = ""
            reg_titles[f"tracks.{track_id}.course_id"] = (
                    prefix + rs.gettext("Course"))
            reg_choices[f"tracks.{track_id}.course_id"] = course_entries
            reg_titles[f"tracks.{track_id}.course_instructor"] = (
                    prefix + rs.gettext("Instructor"))
            reg_choices[f"tracks.{track_id}.course_instructor"] = course_entries
            reg_titles[f"tracks.{track_id}.choices"] = (
                    prefix + rs.gettext("Course Choices"))
            reg_choices[f"tracks.{track_id}.choices"] = course_entries
            course_titles[f"segments.{track_id}"] = (
                    prefix + rs.gettext("Status"))
            course_choices[f"segments.{track_id}"] = segment_stati_entries

        for field in event['fields'].values():
            # TODO add choices?
            key = f"fields.{field['field_name']}"
            title = safe_filter("<i>{}</i>").format(field['field_name'])
            if field['association'] == const.FieldAssociations.registration:
                reg_titles[key] = title
            elif field['association'] == const.FieldAssociations.course:
                course_titles[key] = title
            elif field['association'] == const.FieldAssociations.lodgement:
                lodgement_titles[key] = title

        # Titles and choices for part-specific fields
        for part_id, part in event['parts'].items():
            if len(event['parts']) > 1:
                prefix = f"{part['shortname']}: "
            else:
                prefix = ""
            reg_titles[f"parts.{part_id}.status"] = (
                    prefix + rs.gettext("Status"))
            reg_choices[f"parts.{part_id}.status"] = reg_part_stati_entries
            reg_titles[f"parts.{part_id}.lodgement_id"] = (
                    prefix + rs.gettext("Lodgement"))
            reg_choices[f"parts.{part_id}.lodgement_id"] = lodgement_entries
            reg_titles[f"parts.{part_id}.is_camping_mat"] = (
                    prefix + rs.gettext("Camping Mat"))

        return (reg_titles, reg_choices, course_titles, course_choices,
                lodgement_titles)

    @access("event")
    @REQUESTdata("preview")
    def register_form(self, rs: RequestState, event_id: int,
                      preview: bool = False) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'],
            event['begin'])
        minor_form = self.eventproxy.get_minor_form(rs, event_id)
        rs.ignore_validation_errors()
        if not preview:
            if rs.user.persona_id in registrations.values():
                rs.notify("info", n_("Already registered."))
                return self.redirect(rs, "event/registration_status")
            if not event['is_open']:
                rs.notify("warning", n_("Registration not open."))
                return self.redirect(rs, "event/show_event")
            if self.is_locked(event):
                rs.notify("warning", n_("Event locked."))
                return self.redirect(rs, "event/show_event")
            if rs.ambience['event']['is_archived']:
                rs.notify("error", n_("Event is already archived."))
                return self.redirect(rs, "event/show_event")
            if not minor_form and age.is_minor():
                rs.notify("info", n_("No minors may register. "
                                     "Please contact the Orgateam."))
                return self.redirect(rs, "event/show_event")
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    n_("Must be Orga to use preview."))
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']
                           or (not event['is_course_state_visible']
                               and track_id in course['segments'])]
            for track_id in tracks}
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        # by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', event['parts'])
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "register", {
            'persona': persona, 'age': age, 'courses': courses,
            'course_choices': course_choices, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'preview': preview})

    @staticmethod
    def process_registration_input(
            rs: RequestState, event: CdEDBObject, courses: CdEDBObjectMap,
            reg_questionnaire: Collection[CdEDBObject],
            parts: CdEDBObjectMap = None) -> CdEDBObject:
        """Helper to handle input by participants.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event.

        :param parts: If not None this specifies the ids of the parts this
          registration applies to (since you can apply for only some of the
          parts of an event and should not have to choose courses for the
          non-relevant parts this is important). If None the parts have to
          be provided in the input.
        :returns: registration data set
        """
        tracks = event['tracks']
        standard_params: TypeMapping = {
            "mixed_lodging": bool,
            "notes": Optional[str],  # type: ignore
            "list_consent": bool
        }
        if parts is None:
            standard_params["parts"] = Collection[int]  # type: ignore
        standard = request_extractor(rs, standard_params)
        if parts is not None:
            standard['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params: TypeMapping = {
            f"course_choice{track_id}_{i}": Optional[vtypes.ID]  # type: ignore
            for part_id in standard['parts']
            for track_id in event['parts'][part_id]['tracks']
            for i in range(event['tracks'][track_id]['num_choices'])
        }
        choices = request_extractor(rs, choice_params)
        instructor_params: TypeMapping = {
            f"course_instructor{track_id}": Optional[vtypes.ID]  # type: ignore
            for part_id in standard['parts']
            for track_id in event['parts'][part_id]['tracks']
        }
        instructor = request_extractor(rs, instructor_params)
        if not standard['parts']:
            rs.append_validation_error(
                ("parts", ValueError(n_("Must select at least one part."))))
        present_tracks = set()
        choice_getter = (
            lambda track_id, i: choices[f"course_choice{track_id}_{i}"])
        for part_id in standard['parts']:
            for track_id, track in event['parts'][part_id]['tracks'].items():
                present_tracks.add(track_id)
                # Check for duplicate course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, j),
                     ValueError(n_("You cannot have the same course as %(i)s."
                                   " and %(j)s. choice"), {'i': i+1, 'j': j+1}))
                    for j in range(track['num_choices'])
                    for i in range(j)
                    if (choice_getter(track_id, j) is not None
                        and choice_getter(track_id, i)
                            == choice_getter(track_id, j)))
                # Check for unfilled mandatory course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, i),
                     ValueError(n_("You must choose at least %(min_choices)s"
                                   " courses."),
                                {'min_choices': track['min_choices']}))
                    for i in range(track['min_choices'])
                    if choice_getter(track_id, i) is None)
        reg_parts: CdEDBObjectMap = {part_id: {} for part_id in event['parts']}
        if parts is None:
            for part_id in reg_parts:
                stati = const.RegistrationPartStati
                if part_id in standard['parts']:
                    reg_parts[part_id]['status'] = stati.applied
                else:
                    reg_parts[part_id]['status'] = stati.not_applied
        reg_tracks = {
            track_id: {
                'course_instructor':
                    instructor.get("course_instructor{}".format(track_id))
                    if track['num_choices'] else None,
            }
            for track_id, track in tracks.items()
        }
        for track_id in present_tracks:
            reg_tracks[track_id]['choices'] = tuple(
                choice_getter(track_id, i)
                for i in range(tracks[track_id]['num_choices'])
                if choice_getter(track_id, i) is not None)

        f = lambda entry: rs.ambience['event']['fields'][entry['field_id']]
        params: TypeMapping = {
            f(entry)['field_name']: VALIDATOR_LOOKUP[
                const.FieldDatatypes(f(entry)['kind']).name]
            for entry in reg_questionnaire
            if entry['field_id'] and not entry['readonly']
        }
        field_data = request_extractor(rs, params)

        registration = {
            'mixed_lodging': standard['mixed_lodging'],
            'list_consent': standard['list_consent'],
            'notes': standard['notes'],
            'parts': reg_parts,
            'tracks': reg_tracks,
            'fields': field_data,
        }
        return registration

    @access("event", modi={"POST"})
    def register(self, rs: RequestState, event_id: int) -> Response:
        """Register for an event."""
        if not rs.ambience['event']['is_open']:
            rs.notify("error", n_("Registration not open."))
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/show_event")
        if rs.ambience['event']['is_archived']:
            rs.notify("warning", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, reg_questionnaire)
        if rs.has_validation_errors():
            return self.register_form(rs, event_id)
        registration['event_id'] = event_id
        registration['persona_id'] = rs.user.persona_id
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        minor_form = self.eventproxy.get_minor_form(rs, event_id)
        if not minor_form and age.is_minor():
            rs.notify("error", n_("No minors may register. "
                                  "Please contact the Orgateam."))
            return self.redirect(rs, "event/show_event")
        registration['parental_agreement'] = not age.is_minor()
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration)
        meta_info = self.coreproxy.get_meta_info(rs)
        fee = self.eventproxy.calculate_fee(rs, new_id)
        semester_fee = self.conf["MEMBERSHIP_FEE"]

        subject = "Anmeldung für {}".format(rs.ambience['event']['title'])
        reply_to = (rs.ambience['event']['orga_address'] or
                    self.conf["EVENT_ADMIN_ADDRESS"])
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': subject,
             'Reply-To': reply_to},
            {'fee': fee, 'age': age, 'meta_info': meta_info,
             'semester_fee': semester_fee, 'reference': reference})
        self.notify_return_code(rs, new_id, success=n_("Registered for event."))
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def registration_status(self, rs: RequestState, event_id: int) -> Response:
        """Present current state of own registration."""
        reg_list = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not reg_list:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(reg_list.keys())
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        semester_fee = self.conf["MEMBERSHIP_FEE"]
        part_order = xsorted(
            registration['parts'].keys(),
            key=lambda anid:
                rs.ambience['event']['parts'][anid]['part_begin'])
        registration['parts'] = OrderedDict(
            (part_id, registration['parts'][part_id]) for part_id in part_order)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, (const.QuestionnaireUsages.registration,)))
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=rs.user.persona_id)
        return self.render(rs, "registration_status", {
            'registration': registration, 'age': age, 'courses': courses,
            'meta_info': meta_info, 'fee': fee, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire, 'reference': reference,
            'waitlist_position': waitlist_position,
        })

    @access("event")
    def amend_registration_form(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys())
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if event['is_archived']:
            rs.notify("warning", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        if (event['registration_soft_limit'] and
                now() > event['registration_soft_limit']):
            rs.notify("warning",
                      n_("Registration closed, no changes possible."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']
                           or (not event['is_course_state_visible']
                               and track_id in course['segments'])]
            for track_id in tracks}
        non_trivials = {}
        for track_id, track in registration['tracks'].items():
            for i, choice in enumerate(track['choices']):
                param = "course_choice{}_{}".format(track_id, i)
                non_trivials[param] = choice
        for track_id, entry in registration['tracks'].items():
            param = "course_instructor{}".format(track_id)
            non_trivials[param] = entry['course_instructor']
        for k, v in registration['fields'].items():
            non_trivials[k] = v
        stat = lambda track: registration['parts'][track['part_id']]['status']
        involved_tracks = {
            track_id for track_id, track in tracks.items()
            if const.RegistrationPartStati(stat(track)).is_involved()}
        merge_dicts(rs.values, non_trivials, registration)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        return self.render(rs, "amend_registration", {
            'age': age, 'courses': courses, 'course_choices': course_choices,
            'involved_tracks': involved_tracks,
            'reg_questionnaire': reg_questionnaire,
        })

    @access("event", modi={"POST"})
    def amend_registration(self, rs: RequestState, event_id: int) -> Response:
        """Change information provided during registering.

        Participants are not able to change for which parts they applied on
        purpose. For this they have to communicate with the orgas.
        """
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id).keys())
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if (rs.ambience['event']['registration_soft_limit'] and
                now() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("error", n_("No changes allowed anymore."))
            return self.redirect(rs, "event/registration_status")
        if rs.ambience['event']['is_archived']:
            rs.notify("error", n_("Event is already archived."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        stored = self.eventproxy.get_registration(rs, registration_id)
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, reg_questionnaire,
            parts=stored['parts'])
        if rs.has_validation_errors():
            return self.amend_registration_form(rs, event_id)

        registration['id'] = registration_id
        persona = self.coreproxy.get_event_user(
            rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        code = self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    @event_guard(check_offline=True)
    def configure_registration_form(self, rs: RequestState, event_id: int
                                    ) -> Response:
        """Render form."""
        reg_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.registration)
        return self.render(rs, "configure_registration",
                           {'reg_questionnaire': reg_questionnaire,
                            'registration_fields': reg_fields})

    @access("event")
    @event_guard(check_offline=True)
    def configure_additional_questionnaire_form(self, rs: RequestState,
                                                event_id: int) -> Response:
        """Render form."""
        add_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.additional)
        return self.render(rs, "configure_additional_questionnaire", {
            'add_questionnaire': add_questionnaire,
            'registration_fields': reg_fields})

    def _prepare_questionnaire_form(self, rs: RequestState, event_id: int,
                                    kind: const.QuestionnaireUsages
                                    ) -> Tuple[List[CdEDBObject],
                                               CdEDBObjectMap]:
        """Helper to retrieve some data for questionnaire configuration."""
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        current = {
            "{}_{}".format(key, i): value
            for i, entry in enumerate(questionnaire)
            for key, value in entry.items()}
        merge_dicts(rs.values, current)
        registration_fields = {
            k: v for k, v in rs.ambience['event']['fields'].items()
            if v['association'] == const.FieldAssociations.registration}
        return questionnaire, registration_fields

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def configure_registration(self, rs: RequestState, event_id: int
                               ) -> Response:
        """Manipulate the questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.registration
        code = self._set_questionnaire(rs, event_id, kind)
        if code is None:
            return self.configure_registration_form(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/configure_registration_form")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def configure_additional_questionnaire(self, rs: RequestState,
                                           event_id: int) -> Response:
        """Manipulate the additional questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        kind = const.QuestionnaireUsages.additional
        code = self._set_questionnaire(rs, event_id, kind)
        if code is None:
            return self.configure_additional_questionnaire_form(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(
            rs, "event/configure_additional_questionnaire_form")

    def _set_questionnaire(self, rs: RequestState, event_id: int,
                           kind: const.QuestionnaireUsages
                           ) -> Optional[DefaultReturnCode]:
        """Deduplicated code to set questionnaire rows of one kind."""
        other_kinds = set()
        for x in const.QuestionnaireUsages:
            if x != kind:
                other_kinds.add(x)
        old_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        other_questionnaire = self.eventproxy.get_questionnaire(
            rs, event_id, kinds=other_kinds)
        other_used_fields = {e['field_id'] for v in other_questionnaire.values()
                             for e in v if e['field_id']}
        registration_fields = {
            k: v for k, v in rs.ambience['event']['fields'].items()
            if v['association'] == const.FieldAssociations.registration}

        new_questionnaire = self.process_questionnaire_input(
            rs, len(old_questionnaire), registration_fields, kind,
            other_used_fields)
        if rs.has_validation_errors():
            return None
        code = self.eventproxy.set_questionnaire(
            rs, event_id, new_questionnaire)
        return code

    @access("event")
    @REQUESTdata("preview")
    def additional_questionnaire_form(self, rs: RequestState, event_id: int,
                                      preview: bool = False,
                                      internal: bool = False) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, "event/show_event")
        if not preview:
            registration_id = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id)
            if not registration_id:
                rs.notify("warning", n_("Not registered for event."))
                return self.redirect(rs, "event/show_event")
            registration_id = unwrap(registration_id.keys())
            registration = self.eventproxy.get_registration(rs, registration_id)
            if not rs.ambience['event']['use_additional_questionnaire']:
                rs.notify("warning", n_("Questionnaire disabled."))
                return self.redirect(rs, "event/registration_status")
            if self.is_locked(rs.ambience['event']):
                rs.notify("info", n_("Event locked."))
            merge_dicts(rs.values, registration['fields'])
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    n_("Must be Orga to use preview."))
            if not rs.ambience['event']['use_additional_questionnaire']:
                rs.notify("info", n_("Questionnaire is not enabled yet."))
        add_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.additional,)))
        return self.render(rs, "additional_questionnaire", {
            'add_questionnaire': add_questionnaire,
            'preview': preview})

    @access("event", modi={"POST"})
    def additional_questionnaire(self, rs: RequestState, event_id: int
                                 ) -> Response:
        """Fill in additional fields.

        Save data submitted in the additional questionnaire.
        Note that questionnaire rows may also be present during registration.
        """
        registration_id = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(registration_id.keys())
        if not rs.ambience['event']['use_additional_questionnaire']:
            rs.notify("error", n_("Questionnaire disabled."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        if rs.ambience['event']['is_archived']:
            rs.notify("error", n_("Event is already archived."))
            return self.redirect(rs, "event/show_event")
        add_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.additional,)))
        f = lambda entry: rs.ambience['event']['fields'][entry['field_id']]
        params: TypeMapping = {
            f(entry)['field_name']: Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(f(entry)['kind']).name]]
            for entry in add_questionnaire
            if entry['field_id'] and not entry['readonly']
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.additional_questionnaire_form(
                rs, event_id, internal=True)

        code = self.eventproxy.set_registration(rs, {
            'id': registration_id, 'fields': data,
        })
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/additional_questionnaire_form")

    @staticmethod
    def process_questionnaire_input(rs: RequestState, num: int,
                                    reg_fields: Mapping[int, Mapping[str, Any]],
                                    kind: const.QuestionnaireUsages,
                                    other_used_fields: Collection[int]
                                    ) -> Dict[const.QuestionnaireUsages,
                                              List[CdEDBObject]]:
        """This handles input to configure questionnaires.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :param num: number of rows to expect
        :param reg_fields: Available fields
        :param kind: For which kind of questionnaire are these rows?
        """
        del_flags = request_extractor(rs, {f"delete_{i}": bool for i in range(num)})
        deletes = {i for i in range(num) if del_flags['delete_{}'.format(i)]}
        spec: TypeMapping = {
            'field_id': Optional[vtypes.ID],  # type: ignore
            'title': Optional[str],  # type: ignore
            'info': Optional[str],  # type: ignore
            'input_size': Optional[int],  # type: ignore
            'readonly': Optional[bool],  # type: ignore
            'default_value': Optional[str],  # type: ignore
        }
        marker = 1
        while marker < 2 ** 10:
            if not unwrap(request_extractor(rs, {f"create_-{marker}": bool})):
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        indices = (set(range(num)) | {-i for i in range(1, marker)}) - deletes

        field_key = lambda anid: f"field_id_{anid}"
        readonly_key = lambda anid: f"readonly_{anid}"
        default_value_key = lambda anid: f"default_value_{anid}"

        def duplicate_constraint(idx1: int, idx2: int
                                 ) -> Optional[RequestConstraint]:
            if idx1 == idx2:
                return None
            key1 = field_key(idx1)
            key2 = field_key(idx2)
            msg = n_("Must not duplicate field.")
            return (lambda d: (not d[key1] or d[key1] != d[key2]),
                    (key1, ValueError(msg)))

        def valid_field_constraint(idx: int) -> RequestConstraint:
            key = field_key(idx)
            return (lambda d: not d[key] or d[key] in reg_fields,
                    (key, ValueError(n_("Invalid field."))))

        def fee_modifier_kind_constraint(idx: int) -> RequestConstraint:
            key = field_key(idx)
            msg = n_("Fee modifier field may only be used in"
                     " registration questionnaire.")
            fee_modifier_fields = {
                e['field_id'] for
                e in rs.ambience['event']['fee_modifiers'].values()}
            valid_usages = {const.QuestionnaireUsages.registration.value}
            return (lambda d: not (d[key] in fee_modifier_fields
                                   and kind not in valid_usages),
                    (key, ValueError(msg)))

        def readonly_kind_constraint(idx: int) -> RequestConstraint:
            key = readonly_key(idx)
            msg = n_("Registration questionnaire rows may not be readonly.")
            return (lambda d: (not d[key] or kind.allow_readonly()),
                    (key, ValueError(msg)))

        def duplicate_kind_constraint(idx: int) -> RequestConstraint:
            key = field_key(idx)
            msg = n_("This field is already in use in another questionnaire.")
            return (lambda d: d[key] not in other_used_fields,
                    (key, ValueError(msg)))

        constraints: List[Tuple[Callable[[CdEDBObject], bool], Error]]
        constraints = list(filter(
            None, (duplicate_constraint(idx1, idx2)
                   for idx1 in indices for idx2 in indices)))
        constraints += list(itertools.chain.from_iterable(
            (valid_field_constraint(idx),
             fee_modifier_kind_constraint(idx),
             readonly_kind_constraint(idx),
             duplicate_kind_constraint(idx))
            for idx in indices))

        params: TypeMapping = {
            f"{key}_{i}": value for i in indices for key, value in spec.items()}
        data = request_extractor(rs, params, constraints)
        for idx in indices:
            dv_key = default_value_key(idx)
            field_id = data[field_key(idx)]
            if data[dv_key] is None or field_id is None:
                data[dv_key] = None
                continue
            data[dv_key] = check_optional(rs, vtypes.ByFieldDatatype,
                data[dv_key], dv_key, kind=reg_fields[field_id]['kind'])
        questionnaire = {
            kind: list(
                {key: data["{}_{}".format(key, i)] for key in spec}
                for i in mixed_existence_sorter(indices))}
        return questionnaire

    @staticmethod
    def _sanitize_questionnaire_row(row: CdEDBObject) -> CdEDBObject:
        """Small helper to make validation happy.

        The invokation
        ``proxy.set_questionnaire(proxy.get_questionnaire())`` fails since
        the retrieval method provides additional information which not
        settable and thus filtered by this method.
        """
        whitelist = ('field_id', 'title', 'info', 'input_size', 'readonly',
                     'default_value', 'kind')
        return {k: v for k, v in row.items() if k in whitelist}

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("kind")
    def reorder_questionnaire_form(self, rs: RequestState, event_id: int,
                                   kind: const.QuestionnaireUsages) -> Response:
        """Render form."""
        if rs.has_validation_errors():
            if any(field == 'kind' for field, _ in rs.retrieve_validation_errors()):
                rs.notify("error", n_("Unknown questionnaire kind."))
                return self.redirect(rs, "event/show_event")
            else:
                # we want to render the errors from reorder_questionnaire on this page,
                # so we only redirect to another page if 'kind' does not pass validation
                pass
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        redirects = {
            const.QuestionnaireUsages.registration:
                "event/configure_registration",
            const.QuestionnaireUsages.additional:
                "event/configure_additional_questionnaire",
        }
        if not questionnaire:
            rs.notify("info", n_("No questionnaire rows of this kind found."))
            return self.redirect(rs, redirects[kind])
        return self.render(rs, "reorder_questionnaire", {
            'questionnaire': questionnaire, 'kind': kind, 'redirect': redirects[kind]})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("order", "kind")
    def reorder_questionnaire(self, rs: RequestState, event_id: int,
                              kind: const.QuestionnaireUsages,
                              order: vtypes.IntCSVList) -> Response:
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))

        if not set(order) == set(range(len(questionnaire))):
            rs.append_validation_error(
                ("order", ValueError(n_("Every row must occur exactly once."))))
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind=kind)

        new_questionnaire = [self._sanitize_questionnaire_row(questionnaire[i])
                             for i in order]
        code = self.eventproxy.set_questionnaire(rs, event_id, {kind: new_questionnaire})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/reorder_questionnaire_form", {'kind': kind})

    @access("event")
    @event_guard()
    def show_registration(self, rs: RequestState, event_id: int,
                          registration_id: int) -> Response:
        """Display all information pertaining to one registration."""
        persona = self.coreproxy.get_event_user(
            rs, rs.ambience['registration']['persona_id'], event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        meta_info = self.coreproxy.get_meta_info(rs)
        reference = make_event_fee_reference(persona, rs.ambience['event'])
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        waitlist_position = self.eventproxy.get_waitlist_position(
            rs, event_id, persona_id=persona['id'])
        return self.render(rs, "show_registration", {
            'persona': persona, 'age': age, 'courses': courses,
            'lodgements': lodgements, 'meta_info': meta_info, 'fee': fee,
            'reference': reference, 'waitlist_position': waitlist_position,
        })

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("skip")
    def change_registration_form(self, rs: RequestState, event_id: int,
                                 registration_id: int, skip: Collection[str],
                                 internal: bool = False) -> Response:
        """Render form.

        The skip parameter is meant to hide certain fields and skip them when
        evaluating the submitted from in change_registration(). This can be
        used in situations, where changing those fields could override
        concurrent changes (e.g. the Check-in).


        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, 'event/show_registration')
        tracks = rs.ambience['event']['tracks']
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_event_user(rs, registration['persona_id'],
                                                event_id)
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['segments']]
            for track_id in tracks}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        reg_values = {"reg.{}".format(key): value
                      for key, value in registration.items()}
        part_values = []
        for part_id, part in registration['parts'].items():
            one_part = {
                "part{}.{}".format(part_id, key): value
                for key, value in part.items()}
            part_values.append(one_part)
        track_values = []
        for track_id, track in registration['tracks'].items():
            one_track = {
                "track{}.{}".format(track_id, key): value
                for key, value in track.items()
                if key != "choices"}
            for i, choice in enumerate(track['choices']):
                key = 'track{}.course_choice_{}'.format(track_id, i)
                one_track[key] = choice
            track_values.append(one_track)
        field_values = {
            "fields.{}".format(key): value
            for key, value in registration['fields'].items()}
        # Fix formatting of ID
        reg_values['reg.real_persona_id'] = cdedbid_filter(
            reg_values['reg.real_persona_id'])
        merge_dicts(rs.values, reg_values, field_values,
                    *(part_values + track_values))
        return self.render(rs, "change_registration", {
            'persona': persona, 'courses': courses,
            'course_choices': course_choices, 'lodgements': lodgements,
            'skip': skip or []})

    @staticmethod
    def process_orga_registration_input(
            rs: RequestState, event: CdEDBObject, do_fields: bool = True,
            check_enabled: bool = False, skip: Collection[str] = (),
            do_real_persona_id: bool = False) -> CdEDBObject:
        """Helper to handle input by orgas.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event. This puts less restrictions
        on the input (like not requiring different course choices).

        :param do_fields: Process custom fields of the registration(s)
        :param check_enabled: Check if the "enable" checkboxes, corresponding
                              to the fields are set. This is required for the
                              multiedit page.
        :param skip: A list of field names to be entirely skipped
        :param do_real_persona_id: Process the `real_persona_id` field. Should
                                   only be done when CDEDB_OFFLINE_DEPLOYMENT
        :returns: registration data set
        """

        def filter_parameters(params: TypeMapping) -> TypeMapping:
            """Helper function to filter parameters by `skip` list and `enabled`
            checkboxes"""
            params = {key: kind for key, kind in params.items() if key not in skip}
            if not check_enabled:
                return params
            enable_params = {f"enable_{i}": bool for i, t in params.items()}
            enable = request_extractor(rs, enable_params)
            return {
                key: kind for key, kind in params.items() if enable[f"enable_{key}"]}

        # Extract parameters from request
        tracks = event['tracks']
        reg_params: TypeMapping = {
            "reg.notes": Optional[str],  # type: ignore
            "reg.orga_notes": Optional[str],  # type: ignore
            "reg.payment": Optional[datetime.date],  # type: ignore
            "reg.amount_paid": vtypes.NonNegativeDecimal,
            "reg.parental_agreement": bool,
            "reg.mixed_lodging": bool,
            "reg.checkin": Optional[datetime.datetime],  # type: ignore
            "reg.list_consent": bool,
        }
        part_params: TypeMapping = {}
        for part_id in event['parts']:
            part_params.update({  # type: ignore
                f"part{part_id}.status": const.RegistrationPartStati,
                f"part{part_id}.lodgement_id": Optional[vtypes.ID],
                f"part{part_id}.is_camping_mat": bool
            })
        track_params: TypeMapping = {}
        for track_id, track in tracks.items():
            track_params.update({  # type: ignore
                f"track{track_id}.{key}": Optional[vtypes.ID]
                for key in ("course_id", "course_instructor")
            })
            track_params.update({  # type: ignore
                f"track{track_id}.course_choice_{i}": Optional[vtypes.ID]
                for i in range(track['num_choices'])
            })
        field_params: TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for field in event['fields'].values()
            if field['association'] == const.FieldAssociations.registration
        }

        raw_reg = request_extractor(rs, filter_parameters(reg_params))
        if do_real_persona_id:
            raw_reg.update(request_extractor(rs, filter_parameters({
                "reg.real_persona_id": Optional[vtypes.CdedbID]  # type: ignore
            })))
        raw_parts = request_extractor(rs, filter_parameters(part_params))
        raw_tracks = request_extractor(rs, filter_parameters(track_params))
        raw_fields = request_extractor(rs, filter_parameters(field_params))

        # Build `parts`, `tracks` and `fields` dict
        new_parts = {
            part_id: {
                key: raw_parts["part{}.{}".format(part_id, key)]
                for key in ("status", "lodgement_id", "is_camping_mat")
                if "part{}.{}".format(part_id, key) in raw_parts
            }
            for part_id in event['parts']
        }
        new_tracks = {
            track_id: {
                key: raw_tracks["track{}.{}".format(track_id, key)]
                for key in ("course_id", "course_instructor")
                if "track{}.{}".format(track_id, key) in raw_tracks
            }
            for track_id in tracks
        }
        # Build course choices (but only if all choices are present)
        for track_id, track in tracks.items():
            if not all("track{}.course_choice_{}".format(track_id, i)
                       in raw_tracks
                       for i in range(track['num_choices'])):
                continue
            extractor = lambda i: raw_tracks["track{}.course_choice_{}".format(
                track_id, i)]
            choices_tuple = tuple(
                extractor(i)
                for i in range(track['num_choices']) if extractor(i))
            choices_set = set(choices_tuple)
            if len(choices_set) != len(choices_tuple):
                rs.extend_validation_errors(
                    ("track{}.course_choice_{}".format(track_id, i),
                     ValueError(n_("Must choose different courses.")))
                    for i in range(track['num_choices']))
            new_tracks[track_id]['choices'] = choices_tuple
        new_fields = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}

        # Put it all together
        registration = {
            key.split('.', 1)[1]: value for key, value in raw_reg.items()}
        registration['parts'] = new_parts
        registration['tracks'] = new_tracks
        if do_fields:
            registration['fields'] = new_fields
        return registration

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("skip")
    def change_registration(self, rs: RequestState, event_id: int,
                            registration_id: int, skip: Collection[str]
                            ) -> Response:
        """Make privileged changes to any information pertaining to a
        registration.

        Strictly speaking this makes a lot of the other functionality
        redundant (like managing the lodgement inhabitants), but it would be
        much more cumbersome to always use this interface.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], skip=skip,
            do_real_persona_id=self.conf["CDEDB_OFFLINE_DEPLOYMENT"])
        if rs.has_validation_errors():
            return self.change_registration_form(
                rs, event_id, registration_id, skip=(), internal=True)
        registration['id'] = registration_id
        code = self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_registration")

    @access("event")
    @event_guard(check_offline=True)
    def add_registration_form(self, rs: RequestState, event_id: int
                              ) -> Response:
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        registrations = self.eventproxy.list_registrations(rs, event_id)
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['active_segments']]
            for track_id in tracks}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        defaults = {
            "part{}.status".format(part_id):
                const.RegistrationPartStati.participant.value
            for part_id in rs.ambience['event']['parts']
        }
        merge_dicts(rs.values, defaults)
        return self.render(rs, "add_registration", {
            'courses': courses, 'course_choices': course_choices,
            'lodgements': lodgements,
            'registered_personas': registrations.values()})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def add_registration(self, rs: RequestState, event_id: int) -> Response:
        """Register a participant by an orga.

        This should not be used that often, since a registration should
        singnal legal consent which is not provided this way.
        """
        persona_id = unwrap(
            request_extractor(rs, {"persona.persona_id": vtypes.CdedbID}))
        if persona_id is not None:
            if not self.coreproxy.verify_id(rs, persona_id, is_archived=False):
                rs.append_validation_error(
                    ("persona.persona_id", ValueError(n_(
                        "This user does not exist or is archived."))))
            elif not self.coreproxy.verify_persona(rs, persona_id, {"event"}):
                rs.append_validation_error(
                    ("persona.persona_id", ValueError(n_(
                        "This user is not an event user."))))
        if (not rs.has_validation_errors()
                and self.eventproxy.list_registrations(rs, event_id,
                                                       persona_id=persona_id)):
            rs.append_validation_error(
                ("persona.persona_id",
                  ValueError(n_("Already registered."))))
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], do_fields=False,
            do_real_persona_id=self.conf["CDEDB_OFFLINE_DEPLOYMENT"])
        if (not rs.has_validation_errors()
                and not self.eventproxy.check_orga_addition_limit(
                    rs, event_id)):
            rs.append_validation_error(
                ("persona.persona_id",
                  ValueError(n_("Rate-limit reached."))))
        if rs.has_validation_errors():
            return self.add_registration_form(rs, event_id)

        registration['persona_id'] = persona_id
        registration['event_id'] = event_id
        new_id = self.eventproxy.create_registration(rs, registration)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_registration(self, rs: RequestState, event_id: int,
                            registration_id: int, ack_delete: bool) -> Response:
        """Remove a registration."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        # maybe exclude some blockers
        code = self.eventproxy.delete_registration(
            rs, registration_id, {"registration_parts", "registration_tracks",
                                  "course_choices"})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_query")

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("reg_ids")
    def change_registrations_form(self, rs: RequestState, event_id: int,
                                  reg_ids: vtypes.IntCSVList) -> Response:
        """Render form for changing multiple registrations."""

        # Redirect, if the reg_ids parameters is error-prone, to avoid backend
        # errors. Other errors are okay, since they can occur on submitting the
        # form
        if (rs.has_validation_errors()
                and all(field == 'reg_ids'
                        for field, _ in rs.retrieve_validation_errors())):
            return self.redirect(rs, 'event/registration_query',
                                 {'download': None, 'is_search': False})
        # Get information about registrations, courses and lodgements
        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, reg_ids)
        if not registrations:
            rs.notify("error", n_("No participants found to edit."))
            return self.redirect(rs, 'event/registration_query')

        personas = self.coreproxy.get_event_users(
            rs, [r['persona_id'] for r in registrations.values()], event_id)
        for reg_id, reg in registrations.items():
            reg['gender'] = personas[reg['persona_id']]['gender']
        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in keydictsort_filter(courses, EntitySorter.course)
                       if track_id in course['segments']]
            for track_id in tracks}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)

        representative = next(iter(registrations.values()))

        # iterate registrations to check for differing values
        reg_values = {}
        for key, value in representative.items():
            if all(r[key] == value for r in registrations.values()):
                reg_values['reg.{}'.format(key)] = value
                reg_values['enable_reg.{}'.format(key)] = True

        # do the same for registration parts', tracks' and field values
        for part_id in rs.ambience['event']['parts']:
            for key, value in representative['parts'][part_id].items():
                if all(r['parts'][part_id][key] == value for r in
                       registrations.values()):
                    reg_values['part{}.{}'.format(part_id, key)] = value
                    reg_values['enable_part{}.{}'.format(part_id, key)] = True
            for track_id in rs.ambience['event']['parts'][part_id]['tracks']:
                for key, value in representative['tracks'][track_id].items():
                    if all(r['tracks'][track_id][key] == value for r in
                           registrations.values()):
                        reg_values['track{}.{}'.format(track_id, key)] = value
                        reg_values[
                            'enable_track{}.{}'.format(track_id, key)] = True

        for field_id in rs.ambience['event']['fields']:
            key = rs.ambience['event']['fields'][field_id]['field_name']
            present = {r['fields'][key] for r in registrations.values()
                       if key in r['fields']}
            # If none of the registration has a value for this field yet, we
            # consider them equal
            if not present:
                reg_values['enable_fields.{}'.format(key)] = True
            # If all registrations have a value, we have to compare them
            elif len(present) == len(registrations):
                value = representative['fields'][key]
                if all(key in r['fields'] and r['fields'][key] == value
                       for r in registrations.values()):
                    reg_values['enable_fields.{}'.format(key)] = True
                    reg_values['fields.{}'.format(key)] = unwrap(present)

        merge_dicts(rs.values, reg_values)

        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))

        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        return self.render(rs, "change_registrations", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'course_choices': course_choices,
            'lodgements': lodgements})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("reg_ids")
    def change_registrations(self, rs: RequestState, event_id: int,
                             reg_ids: vtypes.IntCSVList) -> Response:
        """Make privileged changes to any information pertaining to multiple
        registrations.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], check_enabled=True)
        if rs.has_validation_errors():
            return self.change_registrations_form(rs, event_id, reg_ids)

        code = 1
        self.logger.info(
            f"Updating registrations {reg_ids} with data {registration}")
        for reg_id in reg_ids:
            registration['id'] = reg_id
            code *= self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)

        # redirect to query filtered by reg_ids
        query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ("reg.id", "persona.given_names", "persona.family_name",
             "persona.username"),
            (("reg.id", QueryOperators.oneof, reg_ids),),
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        return self.redirect(rs, "event/registration_query",
                             querytoparams_filter(query))

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

    @staticmethod
    def check_lodgement_problems(
            event: CdEDBObject, lodgements: CdEDBObjectMap,
            registrations: CdEDBObjectMap, personas: CdEDBObjectMap,
            inhabitants: Dict[Tuple[int, int], Collection[int]]
    ) -> List[LodgementProblem]:
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        :returns: problems as five-tuples of (problem description, lodgement
          id, part id, affected registrations, severeness).
        """
        ret: List[LodgementProblem] = []

        # first some un-inlined code pieces (otherwise nesting is a bitch)
        def _mixed(group: Collection[int]) -> bool:
            """Un-inlined check whether both genders are present."""
            return any({personas[registrations[a]['persona_id']]['gender'],
                        personas[registrations[b]['persona_id']]['gender']} ==
                       {const.Genders.male, const.Genders.female}
                       for a, b in itertools.combinations(group, 2))

        def _mixing_problem(lodgement_id: int, part_id: int
                            ) -> LodgementProblem:
            """Un-inlined code to generate an entry for mixing problems."""
            return LodgementProblem(
                n_("Mixed lodgement with non-mixing participants."),
                lodgement_id, part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if not registrations[reg_id]['mixed_lodging']),
                3)

        def _camping_mat(group: Collection[int], part_id: int) -> int:
            """Un-inlined code to count the number of registrations assigned
            to a lodgement as camping_mat lodgers."""
            return sum(
                registrations[reg_id]['parts'][part_id]['is_camping_mat']
                for reg_id in group)

        def _camping_mat_problem(lodgement_id: int, part_id: int
                                 ) -> LodgementProblem:
            """Un-inlined code to generate an entry for camping_mat problems."""
            return LodgementProblem(
                n_("Too many camping mats used."), lodgement_id,
                part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if registrations[reg_id]['parts'][part_id]['is_camping_mat']),
                1)

        # now the actual work
        for lodgement_id in lodgements:
            for part_id in event['parts']:
                group = inhabitants[(lodgement_id, part_id)]
                lodgement = lodgements[lodgement_id]
                num_camping_mat = _camping_mat(group, part_id)
                if len(group) > (lodgement['regular_capacity'] +
                                 lodgement['camping_mat_capacity']):
                    ret.append(LodgementProblem(
                        n_("Overful lodgement."), lodgement_id, part_id,
                        tuple(), 2))
                elif lodgement['regular_capacity'] < (len(group) -
                                                      num_camping_mat):
                    ret.append(LodgementProblem(
                        n_("Too few camping mats used."), lodgement_id,
                        part_id, tuple(), 2))
                if num_camping_mat > lodgement['camping_mat_capacity']:
                    ret.append(_camping_mat_problem(lodgement_id, part_id))
                if _mixed(group) and any(
                        not registrations[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                complex_gender_people = tuple(
                    reg_id for reg_id in group
                    if (personas[registrations[reg_id]['persona_id']]['gender']
                        in (const.Genders.other, const.Genders.not_specified)))
                if complex_gender_people:
                    ret.append(LodgementProblem(
                        n_("Non-Binary Participant."), lodgement_id, part_id,
                        complex_gender_people, 1))
        return ret

    @access("event")
    @event_guard()
    @REQUESTdata("sort_part_id", "sortkey", "reverse")
    def lodgements(self, rs: RequestState, event_id: int,
                   sort_part_id: vtypes.ID = None, sortkey: LodgementsSortkeys = None,
                   reverse: bool = False) -> Response:
        """Overview of the lodgements of an event.

        This also displays some issues where possibly errors occured.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "event/lodgements")
        parts = rs.ambience['event']['parts']
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()),
            event_id)

        # All inhabitants (regular and camping_mat) of all lodgements and
        # all parts
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id")
        regular_inhabitant_nums = {
            k: sum(1 for r in v
                   if not registrations[r]['parts'][k[1]]['is_camping_mat'])
            for k, v in inhabitants.items()}
        camping_mat_inhabitant_nums = {
            k: sum(1 for r in v
                   if registrations[r]['parts'][k[1]]['is_camping_mat'])
            for k, v in inhabitants.items()}
        problems = self.check_lodgement_problems(
            rs.ambience['event'], lodgements, registrations, personas,
            inhabitants)
        problems_condensed = {}

        # Calculate regular_inhabitant_sum and camping_mat_inhabitant_sum
        # per part
        regular_inhabitant_sum = {}
        camping_mat_inhabitant_sum = {}
        for part_id in parts:
            regular_lodgement_sum = 0
            camping_mat_lodgement_sum = 0
            for lodgement_id in lodgement_ids:
                regular_lodgement_sum += regular_inhabitant_nums[
                    (lodgement_id, part_id)]
                camping_mat_lodgement_sum += camping_mat_inhabitant_nums[
                    (lodgement_id, part_id)]
            regular_inhabitant_sum[part_id] = regular_lodgement_sum
            camping_mat_inhabitant_sum[part_id] = camping_mat_lodgement_sum

        # Calculate sum of lodgement regular and camping mat capacities
        regular_sum = 0
        camping_mat_sum = 0
        for lodgement in lodgements.values():
            regular_sum += lodgement['regular_capacity']
            camping_mat_sum += lodgement['camping_mat_capacity']

        # Calculate problems_condensed (worst problem)
        for lodgement_id, part_id in itertools.product(
                lodgement_ids, parts.keys()):
            problems_here = [p for p in problems
                             if p[1] == lodgement_id and p[2] == part_id]
            problems_condensed[(lodgement_id, part_id)] = (
                max(p[4] for p in problems_here) if problems_here else 0,
                "; ".join(rs.gettext(p[0]) for p in problems_here),)

        # Calculate groups
        grouped_lodgements = {
            group_id: {
                lodgement_id: lodgement
                for lodgement_id, lodgement
                in keydictsort_filter(lodgements, EntitySorter.lodgement)
                if lodgement['group_id'] == group_id
            }
            for group_id, group
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) +
                [(None, None)])  # type: ignore
        }

        # Calculate group_regular_inhabitants_sum,
        #           group_camping_mat_inhabitants_sum,
        #           group_regular_sum and group_camping_mat_sum
        group_regular_inhabitants_sum = {
            (group_id, part_id):
                sum(regular_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_camping_mat_inhabitants_sum = {
            (group_id, part_id):
                sum(camping_mat_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_regular_sum = {
            group_id: sum(lodgement['regular_capacity']
                          for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}
        group_camping_mat_sum = {
            group_id: sum(lodgement['camping_mat_capacity']
                          for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}

        def sort_lodgement(lodgement_tuple: Tuple[int, CdEDBObject],
                           group_id: int) -> Sortkey:
            anid, lodgement = lodgement_tuple
            lodgement_group = grouped_lodgements[group_id]
            primary_sort: Sortkey
            if sortkey is None:
                primary_sort = ()
            elif sortkey.is_used_sorting():
                if sort_part_id not in parts.keys():
                    raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
                assert sort_part_id is not None
                regular = regular_inhabitant_nums[(anid, sort_part_id)]
                camping_mat = camping_mat_inhabitant_nums[(anid, sort_part_id)]
                primary_sort = (
                    regular if sortkey == LodgementsSortkeys.used_regular
                    else camping_mat,)
            elif sortkey.is_total_sorting():
                regular = (lodgement_group[anid]['regular_capacity']
                           if anid in lodgement_group else 0)
                camping_mat = (lodgement_group[anid]['camping_mat_capacity']
                               if anid in lodgement_group else 0)
                primary_sort = (
                    regular if sortkey == LodgementsSortkeys.total_regular
                    else camping_mat,)
            elif sortkey == LodgementsSortkeys.title:
                primary_sort = (lodgement["title"],)
            else:
                primary_sort = ()
            secondary_sort = EntitySorter.lodgement(lodgement)
            return primary_sort + secondary_sort

        # now sort the lodgements inside their group
        sorted_grouped_lodgements = OrderedDict([
            (group_id, OrderedDict([
                (lodgement_id, lodgement)
                for lodgement_id, lodgement
                in xsorted(lodgements.items(), reverse=reverse,
                           key=lambda e: sort_lodgement(e, group_id))  # pylint: disable=cell-var-from-loop
                if lodgement['group_id'] == group_id
            ]))
            for group_id, group
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) +
                [(None, None)])  # type: ignore
        ])

        return self.render(rs, "lodgements", {
            'groups': groups,
            'grouped_lodgements': sorted_grouped_lodgements,
            'regular_inhabitants': regular_inhabitant_nums,
            'regular_inhabitants_sum': regular_inhabitant_sum,
            'group_regular_inhabitants_sum': group_regular_inhabitants_sum,
            'camping_mat_inhabitants': camping_mat_inhabitant_nums,
            'camping_mat_inhabitants_sum': camping_mat_inhabitant_sum,
            'group_camping_mat_inhabitants_sum':
                group_camping_mat_inhabitants_sum,
            'group_regular_sum': group_regular_sum,
            'group_camping_mat_sum': group_camping_mat_sum,
            'regular_sum': regular_sum,
            'camping_mat_sum': camping_mat_sum,
            'problems': problems_condensed,
            'last_sortkey': sortkey,
            'last_sort_part_id': sort_part_id,
            'last_reverse': reverse,
        })

    @access("event")
    @event_guard(check_offline=True)
    def lodgement_group_summary_form(self, rs: RequestState, event_id: int
                                     ) -> Response:
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)

        current = {
            "{}_{}".format(key, group_id): value
            for group_id, group in groups.items()
            for key, value in group.items() if key != 'id'}
        merge_dicts(rs.values, current)

        is_referenced = set()
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        for lodgement in lodgements.values():
            is_referenced.add(lodgement['group_id'])

        return self.render(rs, "lodgement_group_summary", {
            'lodgement_groups': groups, 'is_referenced': is_referenced})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lodgement_group_summary(self, rs: RequestState, event_id: int
                                ) -> Response:
        """Manipulate groups of lodgements."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        spec = {'title': str}
        groups = process_dynamic_input(
            rs, group_ids.keys(), spec, additional={'event_id': event_id})
        if rs.has_validation_errors():
            return self.lodgement_group_summary_form(rs, event_id)
        code = 1
        for group_id, group in groups.items():
            if group is None:
                code *= self.eventproxy.delete_lodgement_group(
                    rs, group_id, cascade=("lodgements",))
            elif group_id < 0:
                code *= self.eventproxy.create_lodgement_group(rs, group)
            else:
                with Atomizer(rs):
                    current = self.eventproxy.get_lodgement_group(rs, group_id)
                    # Do not update unchanged
                    if current != group:
                        code *= self.eventproxy.set_lodgement_group(rs, group)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/lodgement_group_summary")

    @access("event")
    @event_guard()
    def show_lodgement(self, rs: RequestState, event_id: int,
                       lodgement_id: int) -> Response:
        """Display details of one lodgement."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in (self.eventproxy.get_registrations(rs, registration_ids)
                         .items())
            if any(part['lodgement_id'] == lodgement_id
                   for part in v['parts'].values())}
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()),
            event_id)
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)

        problems = self.check_lodgement_problems(
            rs.ambience['event'], {lodgement_id: rs.ambience['lodgement']},
            registrations, personas, inhabitants)

        if not any(reg_ids for reg_ids in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        return self.render(rs, "show_lodgement", {
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,
            'groups': groups,
        })

    @access("event")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs: RequestState, event_id: int
                              ) -> Response:
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        return self.render(rs, "create_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*LODGEMENT_COMMON_FIELDS)
    def create_lodgement(self, rs: RequestState, event_id: int,
                         data: CdEDBObject) -> Response:
        """Add a new lodgement."""
        data['event_id'] = event_id
        field_params: TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, vtypes.Lodgement, data, creation=True)
        if rs.has_validation_errors():
            return self.create_lodgement_form(rs, event_id)
        assert data is not None

        new_id = self.eventproxy.create_lodgement(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event")
    @event_guard(check_offline=True)
    def change_lodgement_form(self, rs: RequestState, event_id: int,
                              lodgement_id: int) -> Response:
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['lodgement']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['lodgement'], field_values)
        return self.render(rs, "change_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdatadict(*LODGEMENT_COMMON_FIELDS)
    def change_lodgement(self, rs: RequestState, event_id: int,
                         lodgement_id: int, data: CdEDBObject) -> Response:
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        data['id'] = lodgement_id
        field_params: TypeMapping = {
            f"fields.{field['field_name']}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement
        }
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, vtypes.Lodgement, data)
        if rs.has_validation_errors():
            return self.change_lodgement_form(rs, event_id, lodgement_id)
        assert data is not None

        code = self.eventproxy.set_lodgement(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_lodgement(self, rs: RequestState, event_id: int,
                         lodgement_id: int, ack_delete: bool) -> Response:
        """Remove a lodgement."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_lodgement(rs, event_id, lodgement_id)
        code = self.eventproxy.delete_lodgement(
            rs, lodgement_id, cascade={"inhabitants"})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/lodgements")

    @access("event")
    @event_guard(check_offline=True)
    def manage_inhabitants_form(self, rs: RequestState, event_id: int,
                                lodgement_id: int) -> Response:
        """Render form."""
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)
        for part_id in rs.ambience['event']['parts']:
            merge_dicts(rs.values, {
                'is_camping_mat_{}_{}'.format(part_id, registration_id):
                    registrations[registration_id]['parts'][part_id][
                        'is_camping_mat']
                for registration_id in inhabitants[(lodgement_id, part_id)]
            })

        def _check_without_lodgement(registration_id: int, part_id: int
                                     ) -> bool:
            """Un-inlined check for registration without lodgement."""
            part = registrations[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(part['status']).is_present()
                    and not part['lodgement_id'])

        without_lodgement = {
            part_id: xsorted(
                (registration_id
                 for registration_id in registrations
                 if _check_without_lodgement(registration_id, part_id)),
                key=lambda anid: EntitySorter.persona(
                    personas[registrations[anid]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }

        # Generate data to be encoded to json and used by the
        # cdedbSearchParticipant() javascript function
        def _check_not_this_lodgement(registration_id: int, part_id: int
                                      ) -> bool:
            """Un-inlined check for registration with different lodgement."""
            part = registrations[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(part['status']).is_present()
                    and part['lodgement_id'] != lodgement_id)

        selectize_data = {
            part_id: xsorted(
                [{'name': (personas[registration['persona_id']]['given_names']
                           + " " + personas[registration['persona_id']]
                           ['family_name']),
                  'current': registration['parts'][part_id]['lodgement_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_lodgement(registration_id, part_id)],
                key=lambda x: (
                    x['current'] is not None,
                    EntitySorter.persona(personas[registrations[x['id']]['persona_id']]))
            )
            for part_id in rs.ambience['event']['parts']
        }
        lodgement_names = self.eventproxy.list_lodgements(rs, event_id)
        other_lodgements = {
            anid: name for anid, name in lodgement_names.items() if anid != lodgement_id
        }
        return self.render(rs, "manage_inhabitants", {
            'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants,
            'without_lodgement': without_lodgement,
            'selectize_data': selectize_data,
            'lodgement_names': lodgement_names,
            'other_lodgements': other_lodgements})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs: RequestState, event_id: int,
                           lodgement_id: int) -> Response:
        """Alter who is assigned to a lodgement.

        This tries to be a bit smart and write only changed state.
        """
        # Get all registrations and current inhabitants
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        current_inhabitants = {
            part_id: [reg_id for reg_id, registration in registrations.items()
                      if registration['parts'][part_id]['lodgement_id']
                      == lodgement_id]
            for part_id in rs.ambience['event']['parts']}
        # Parse request data
        params: TypeMapping = {
            **{
                f"new_{part_id}": Collection[Optional[vtypes.ID]]
                for part_id in rs.ambience['event']['parts']
            },
            **{
                f"delete_{part_id}_{reg_id}": bool
                for part_id in rs.ambience['event']['parts']
                for reg_id in current_inhabitants[part_id]
            },
            **{
                f"is_camping_mat_{part_id}_{reg_id}": bool
                for part_id in rs.ambience['event']['parts']
                for reg_id in current_inhabitants[part_id]
            }
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        # Iterate all registrations to find changed ones
        code = 1
        for reg_id, reg in registrations.items():
            new_reg: CdEDBObject = {
                'id': reg_id,
                'parts': {},
            }
            # Check if registration is new inhabitant or deleted inhabitant
            # in any part
            for part_id in rs.ambience['event']['parts']:
                new_inhabitant = (reg_id in data[f"new_{part_id}"])
                deleted_inhabitant = data.get(
                    "delete_{}_{}".format(part_id, reg_id), False)
                is_camping_mat = reg['parts'][part_id]['is_camping_mat']
                changed_inhabitant = (
                        reg_id in current_inhabitants[part_id]
                        and data.get(f"is_camping_mat_{part_id}_{reg_id}",
                                     False) != is_camping_mat)
                if new_inhabitant or deleted_inhabitant:
                    new_reg['parts'][part_id] = {
                        'lodgement_id': lodgement_id if new_inhabitant else None
                    }
                elif changed_inhabitant:
                    new_reg['parts'][part_id] = {
                        'is_camping_mat': data.get(
                            f"is_camping_mat_{part_id}_{reg_id}",
                            False)
                    }
            if new_reg['parts']:
                code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def swap_inhabitants(self, rs: RequestState, event_id: int,
                         lodgement_id: int) -> Response:
        """Swap inhabitants of two lodgements of the same part."""
        params: TypeMapping = {
            f"swap_with_{part_id}": Optional[vtypes.ID]  # type: ignore
            for part_id in rs.ambience['event']['parts']
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)

        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        inhabitants = self.calculate_groups(
            lodgements.keys(), rs.ambience['event'], registrations, key="lodgement_id")

        new_regs: CdEDBObjectMap = {}
        for part_id in rs.ambience['event']['parts']:
            if data[f"swap_with_{part_id}"]:
                swap_lodgement_id = data[f"swap_with_{part_id}"]
                current_inhabitants = inhabitants[(lodgement_id, part_id)]
                swap_inhabitants = inhabitants[(swap_lodgement_id, part_id)]
                new_reg: CdEDBObject
                for reg_id in current_inhabitants:
                    new_reg = new_regs.get(reg_id, {'id': reg_id, 'parts': dict()})
                    new_reg['parts'][part_id] = {'lodgement_id': swap_lodgement_id}
                    new_regs[reg_id] = new_reg
                for reg_id in swap_inhabitants:
                    new_reg = new_regs.get(reg_id, {'id': reg_id, 'parts': dict()})
                    new_reg['parts'][part_id] = {'lodgement_id': lodgement_id}
                    new_regs[reg_id] = new_reg

        code = 1
        for new_reg in new_regs.values():
            code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event")
    @event_guard(check_offline=True)
    def manage_attendees_form(self, rs: RequestState, event_id: int,
                              course_id: int) -> Response:
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        attendees = self.calculate_groups(
            (course_id,), rs.ambience['event'], registrations, key="course_id",
            personas=personas)

        # Generate options for the multi select boxes
        def _check_without_course(registration_id: int, track_id: int) -> bool:
            """Un-inlined check for registration without course."""
            reg = registrations[registration_id]
            part = reg['parts'][tracks[track_id]['part_id']]
            track = reg['tracks'][track_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and not track['course_id'])

        without_course = {
            track_id: xsorted(
                (registration_id
                 for registration_id in registrations
                 if _check_without_course(registration_id, track_id)),
                key=lambda anid: EntitySorter.persona(
                    personas[registrations[anid]['persona_id']])
            )
            for track_id in tracks
        }

        # Generate data to be encoded to json and used by the
        # cdedbSearchParticipant() javascript function
        def _check_not_this_course(registration_id: int, track_id: int) -> bool:
            """Un-inlined check for registration with different course."""
            reg = registrations[registration_id]
            part = reg['parts'][tracks[track_id]['part_id']]
            track = reg['tracks'][track_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and track['course_id'] != course_id)

        selectize_data = {
            track_id: xsorted(
                [{'name': (personas[registration['persona_id']]['given_names']
                           + " " + personas[registration['persona_id']]
                           ['family_name']),
                  'current': registration['tracks'][track_id]['course_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_course(registration_id, track_id)],
                key=lambda x: (
                    x['current'] is not None,
                    EntitySorter.persona(
                        personas[registrations[x['id']]['persona_id']]))
            )
            for track_id in tracks
        }
        courses = self.eventproxy.list_courses(rs, event_id)
        course_names = {
            course['id']: "{}. {}".format(course['nr'], course['shortname'])
            for course_id, course
            in self.eventproxy.get_courses(rs, courses.keys()).items()
        }

        return self.render(rs, "manage_attendees", {
            'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'without_course': without_course,
            'selectize_data': selectize_data, 'course_names': course_names})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_attendees(self, rs: RequestState, event_id: int, course_id: int
                         ) -> Response:
        """Alter who is assigned to this course."""
        # Get all registrations and especially current attendees of this course
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        current_attendees = {
            track_id: [reg_id for reg_id, registration in registrations.items()
                       if registration['tracks'][track_id]['course_id']
                       == course_id]
            for track_id in rs.ambience['course']['segments']}

        # Parse request data
        params: TypeMapping = {
            **{
                f"new_{track_id}": Collection[Optional[vtypes.ID]]
                for track_id in rs.ambience['course']['segments']
            },
            **{
                f"delete_{track_id}_{reg_id}": bool
                for track_id in rs.ambience['course']['segments']
                for reg_id in current_attendees[track_id]
            }
        }
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_attendees_form(rs, event_id, course_id)

        # Iterate all registrations to find changed ones
        code = 1
        for registration_id, registration in registrations.items():
            new_reg: CdEDBObject = {
                'id': registration_id,
                'tracks': {},
            }
            # Check if registration is new attendee or deleted attendee
            # in any track of the course
            for track_id in rs.ambience['course']['segments']:
                new_attendee = (
                        registration_id in data["new_{}".format(track_id)])
                deleted_attendee = data.get(
                    "delete_{}_{}".format(track_id, registration_id), False)
                if new_attendee or deleted_attendee:
                    new_reg['tracks'][track_id] = {
                        'course_id': (course_id if new_attendee else None)
                    }
            if new_reg['tracks']:
                code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @staticmethod
    def make_registration_query_spec(event: CdEDBObject) -> Dict[str, str]:
        """Helper to enrich ``QUERY_SPECS['qview_registration']``.

        Since each event has dynamic columns for parts and extra fields we
        have amend the query spec on the fly.
        """
        tracks = event['tracks']
        spec = copy.deepcopy(QUERY_SPECS['qview_registration'])
        # note that spec is an ordered dict and we should respect the order
        for part_id, part in keydictsort_filter(event['parts'],
                                                EntitySorter.event_part):
            spec["part{0}.status".format(part_id)] = "int"
            spec["part{0}.is_camping_mat".format(part_id)] = "bool"
            spec["part{0}.lodgement_id".format(part_id)] = "id"
            spec["lodgement{0}.id".format(part_id)] = "id"
            spec["lodgement{0}.group_id".format(part_id)] = "id"
            spec["lodgement{0}.title".format(part_id)] = "str"
            spec["lodgement{0}.notes".format(part_id)] = "str"
            for f in xsorted(event['fields'].values(),
                             key=EntitySorter.event_field):
                if f['association'] == const.FieldAssociations.lodgement:
                    temp = "lodgement{0}.xfield_{1}"
                    kind = const.FieldDatatypes(f['kind']).name
                    spec[temp.format(part_id, f['field_name'])] = kind
            spec["lodgement_group{0}.id".format(part_id)] = "id"
            spec["lodgement_group{0}.title".format(part_id)] = "str"
            ordered_tracks = keydictsort_filter(
                part['tracks'], EntitySorter.course_track)
            for track_id, track in ordered_tracks:
                spec["track{0}.is_course_instructor".format(track_id)] \
                    = "bool"
                spec["track{0}.course_id".format(track_id)] = "int"
                spec["track{0}.course_instructor".format(track_id)] = "int"
                for temp in ("course", "course_instructor",):
                    spec["{1}{0}.id".format(track_id, temp)] = "id"
                    spec["{1}{0}.nr".format(track_id, temp)] = "str"
                    spec["{1}{0}.title".format(track_id, temp)] = "str"
                    spec["{1}{0}.shortname".format(track_id, temp)] = "str"
                    spec["{1}{0}.notes".format(track_id, temp)] = "str"
                    for f in xsorted(event['fields'].values(),
                                     key=EntitySorter.event_field):
                        if f['association'] == const.FieldAssociations.course:
                            key = "{1}{0}.xfield_{2}".format(
                                track_id, temp, f['field_name'])
                            kind = const.FieldDatatypes(f['kind']).name
                            spec[key] = kind
                for i in range(track['num_choices']):
                    spec[f"course_choices{track_id}.rank{i}"] = "int"
                if track['num_choices'] > 1:
                    spec[",".join(f"course_choices{track_id}.rank{i}"
                                  for i in range(track['num_choices']))] = "int"
        if len(event['parts']) > 1:
            spec[",".join("part{0}.status".format(part_id)
                          for part_id in event['parts'])] = "int"
            spec[",".join("part{0}.is_camping_mat".format(part_id)
                          for part_id in event['parts'])] = "bool"
            spec[",".join("part{0}.lodgement_id".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("lodgement{0}.id".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("lodgement{0}.group_id".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("lodgement{0}.title".format(part_id)
                          for part_id in event['parts'])] = "str"
            spec[",".join("lodgement{0}.notes".format(part_id)
                          for part_id in event['parts'])] = "str"
            spec[",".join("lodgement_group{0}.id".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("lodgement_group{0}.title".format(part_id)
                          for part_id in event['parts'])] = "str"
            for f in xsorted(event['fields'].values(),
                             key=EntitySorter.event_field):
                if f['association'] == const.FieldAssociations.lodgement:
                    key = ",".join(
                        "lodgement{0}.xfield_{1}".format(
                            part_id, f['field_name'])
                        for part_id in event['parts'])
                    kind = const.FieldDatatypes(f['kind']).name
                    spec[key] = kind
        if len(tracks) > 1:
            spec[",".join("track{0}.is_course_instructor".format(track_id)
                          for track_id in tracks)] = "bool"
            spec[",".join("track{0}.course_id".format(track_id)
                          for track_id in tracks)] = "bool"
            spec[",".join("track{0}.course_instructor".format(track_id)
                          for track_id in tracks)] = "int"
            for temp in ("course", "course_instructor",):
                spec[",".join("{1}{0}.id".format(track_id, temp)
                              for track_id in tracks)] = "id"
                spec[",".join("{1}{0}.nr".format(track_id, temp)
                              for track_id in tracks)] = "str"
                spec[",".join("{1}{0}.title".format(track_id, temp)
                              for track_id in tracks)] = "str"
                spec[",".join("{1}{0}.shortname".format(track_id, temp)
                              for track_id in tracks)] = "str"
                spec[",".join("{1}{0}.notes".format(track_id, temp)
                              for track_id in tracks)] = "str"
                for f in xsorted(event['fields'].values(),
                                 key=EntitySorter.event_field):
                    if f['association'] == const.FieldAssociations.course:
                        key = ",".join("{1}{0}.xfield_{2}".format(
                            track_id, temp, f['field_name'])
                                       for track_id in tracks)
                        kind = const.FieldDatatypes(f['kind']).name
                        spec[key] = kind
            if sum(track['num_choices'] for track in tracks.values()) > 1:
                spec[",".join(f"course_choices{track_id}.rank{i}"
                              for track_id, track in tracks.items()
                              for i in range(track['num_choices']))] = "int"
        for f in xsorted(event['fields'].values(),
                         key=EntitySorter.event_field):
            if f['association'] == const.FieldAssociations.registration:
                kind = const.FieldDatatypes(f['kind']).name
                spec["reg_fields.xfield_{}".format(f['field_name'])] = kind
        return spec

    # TODO specify return type as OrderedDict.
    @staticmethod
    def make_registration_query_aux(rs: RequestState, event: CdEDBObject,
                                    courses: CdEDBObjectMap,
                                    lodgements: CdEDBObjectMap,
                                    lodgement_groups: CdEDBObjectMap,
                                    fixed_gettext: bool = False
                                    ) -> Tuple[Dict[str, Dict[int, str]],
                                               Dict[str, str]]:
        """Un-inlined code to prepare input for template.
        :param fixed_gettext: whether or not to use a fixed translation
            function. True means static, False means localized.
        :returns: Choices for select inputs and titles for columns.
        """
        tracks = event['tracks']

        if fixed_gettext:
            gettext = rs.default_gettext
            enum_gettext = lambda x: x.name
        else:
            gettext = rs.gettext
            enum_gettext = rs.gettext

        course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
        course_choices = OrderedDict(
            (c_id, course_identifier(c))
            for c_id, c in keydictsort_filter(courses, EntitySorter.course))
        lodge_identifier = lambda l: l["title"]
        lodgement_choices = OrderedDict(
            (l_id, lodge_identifier(l))
            for l_id, l in keydictsort_filter(lodgements,
                                              EntitySorter.lodgement))
        lodgement_group_identifier = lambda g: g["title"]
        lodgement_group_choices = OrderedDict(
            (g_id, lodgement_group_identifier(g))
            for g_id, g in keydictsort_filter(lodgement_groups,
                                              EntitySorter.lodgement_group))
        # First we construct the choices
        choices: Dict[str, Dict[int, str]] = {
            # Genders enum
            'persona.gender': OrderedDict(
                enum_entries_filter(
                    const.Genders, enum_gettext, raw=fixed_gettext)),
        }

        # Precompute some choices
        reg_part_stati_choices = OrderedDict(
            enum_entries_filter(
                const.RegistrationPartStati, enum_gettext, raw=fixed_gettext))
        lodge_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.lodgement
            }
        course_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.course
            }
        reg_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.registration
            }

        for part_id in event['parts']:
            choices.update({
                # RegistrationPartStati enum
                "part{0}.status".format(part_id): reg_part_stati_choices,
                # Lodgement choices for the JS selector
                "part{0}.lodgement_id".format(part_id): lodgement_choices,
                "lodgement{0}.group_id".format(part_id): lodgement_group_choices,
            })
            if not fixed_gettext:
                # Lodgement fields value -> description
                key = "lodgement{0}.xfield_{1}"
                choices.update({
                    key.format(part_id, field['field_name']):
                        OrderedDict(field['entries'])
                    for field in lodge_fields.values() if field['entries']
                })
        for track_id, track in tracks.items():
            choices.update({
                # Course choices for the JS selector
                "track{0}.course_id".format(track_id): course_choices,
                "track{0}.course_instructor".format(track_id): course_choices,
            })
            for i in range(track['num_choices']):
                choices[f"course_choices{track_id}.rank{i}"] = course_choices
            if track['num_choices'] > 1:
                choices[",".join(
                    f"course_choices{track_id}.rank{i}"
                    for i in range(track['num_choices']))] = course_choices
            if not fixed_gettext:
                # Course fields value -> description
                for temp in ("course", "course_instructor"):
                    for field in course_fields.values():
                        key = f"{temp}{track_id}.xfield_{field['field_name']}"
                        if field['entries']:
                            choices[key] = OrderedDict(field['entries'])
        if len(event['parts']) > 1:
            choices.update({
                # RegistrationPartStati enum
                ",".join("part{0}.status".format(part_id)
                         for part_id in event['parts']): reg_part_stati_choices,
                ",".join("part{0}.lodgement_id".format(part_id)
                         for part_id in event['parts']): lodgement_choices,
                ",".join("lodgement{0}.group_id".format(part_id)
                         for part_id in event['parts']): lodgement_group_choices,
            })
        if len(tracks) > 1:
            choices[",".join(f"course_choices{track_id}.rank{i}"
                    for track_id, track in tracks.items()
                    for i in range(track['num_choices']))] = course_choices
        if not fixed_gettext:
            # Registration fields value -> description
            choices.update({
                "reg_fields.xfield_{}".format(field['field_name']):
                    OrderedDict(field['entries'])
                for field in reg_fields.values() if field['entries']
            })

        # Second we construct the titles
        titles: Dict[str, str] = {
            "reg_fields.xfield_{}".format(field['field_name']):
                field['field_name']
            for field in reg_fields.values()
        }
        for track_id, track in tracks.items():
            if len(tracks) > 1:
                prefix = "{shortname}: ".format(shortname=track['shortname'])
            else:
                prefix = ""
            titles.update({
                "track{0}.is_course_instructor".format(track_id):
                    prefix + gettext("instructs their course"),
                "track{0}.course_id".format(track_id):
                    prefix + gettext("course"),
                "track{0}.course_instructor".format(track_id):
                    prefix + gettext("instructed course"),
                "course{0}.id".format(track_id):
                    prefix + gettext("course ID"),
                "course{0}.nr".format(track_id):
                    prefix + gettext("course nr"),
                "course{0}.title".format(track_id):
                    prefix + gettext("course title"),
                "course{0}.shortname".format(track_id):
                    prefix + gettext("course shortname"),
                "course{0}.notes".format(track_id):
                    prefix + gettext("course notes"),
                "course_instructor{0}.id".format(track_id):
                    prefix + gettext("instructed course ID"),
                "course_instructor{0}.nr".format(track_id):
                    prefix + gettext("instructed course nr"),
                "course_instructor{0}.title".format(track_id):
                    prefix + gettext("instructed course title"),
                "course_instructor{0}.shortname".format(track_id):
                    prefix + gettext("instructed course shortname"),
                "course_instructor{0}.notes".format(track_id):
                    prefix + gettext("instructed courese notes"),
            })
            key = "course{0}.xfield_{1}"
            titles.update({
                key.format(track_id, field['field_name']):
                    prefix + gettext("course {field}").format(
                        field=field['field_name'])
                for field in course_fields.values()
            })
            key = "course_instructor{0}.xfield_{1}"
            titles.update({
                key.format(track_id, field['field_name']):
                    prefix + gettext("instructed course {field}").format(
                        field=field['field_name'])
                for field in course_fields.values()
            })
            for i in range(track['num_choices']):
                titles[f"course_choices{track_id}.rank{i}"] = \
                    prefix + gettext("%s. Choice") % (i + 1)
            if track['num_choices'] > 1:
                titles[",".join(f"course_choices{track_id}.rank{i}"
                                for i in range(track['num_choices']))] = \
                    prefix + gettext("Any Choice")
        if len(event['tracks']) > 1:
            titles.update({
                ",".join("track{0}.is_course_instructor".format(track_id)
                         for track_id in tracks):
                    gettext("any track: instructs their course"),
                ",".join("track{0}.course_id".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course"),
                ",".join("track{0}.course_instructor".format(track_id)
                         for track_id in tracks):
                    gettext("any track: instructed course"),
                ",".join("course{0}.id".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course ID"),
                ",".join("course{0}.nr".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course nr"),
                ",".join("course{0}.title".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course title"),
                ",".join("course{0}.shortname".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course shortname"),
                ",".join("course{0}.notes".format(track_id)
                         for track_id in tracks):
                    gettext("any track: course notes"),
                ",".join("course_instructor{0}.id".
                         format(track_id) for track_id in tracks):
                    gettext("any track: instructed course ID"),
                ",".join("course_instructor{0}.nr".
                         format(track_id) for track_id in tracks):
                    gettext("any track: instructed course nr"),
                ",".join("course_instructor{0}.title".
                         format(track_id) for track_id in tracks):
                    gettext("any track: instructed course title"),
                ",".join("course_instructor{0}.shortname".
                         format(track_id) for track_id in tracks):
                    gettext("any track: instructed course shortname"),
                ",".join("course_instructor{0}.notes".format(track_id)
                         for track_id in tracks):
                    gettext("any track: instructed course notes"),
            })
            key = "course{0}.xfield_{1}"
            titles.update({
                ",".join(key.format(track_id, field['field_name'])
                         for track_id in tracks):
                    gettext("any track: course {field}").format(
                        field=field['field_name'])
                for field in course_fields.values()
            })
            key = "course_instructor{0}.xfield_{1}"
            titles.update({
                ",".join(key.format(track_id, field['field_name'])
                         for track_id in tracks):
                    gettext("any track: instructed course {field}").format(
                        field=field['field_name'])
                for field in course_fields.values()
            })
            key = ",".join(f"course_choices{track_id}.rank{i}"
                           for track_id, track in tracks.items()
                           for i in range(track['num_choices']))
            titles[key] = gettext("any track: Any Choice")
        for part_id, part in event['parts'].items():
            if len(event['parts']) > 1:
                prefix = "{shortname}: ".format(shortname=part['shortname'])
            else:
                prefix = ""
            titles.update({
                "part{0}.status".format(part_id):
                    prefix + gettext("registration status"),
                "part{0}.is_camping_mat".format(part_id):
                    prefix + gettext("camping mat user"),
                "part{0}.lodgement_id".format(part_id):
                    prefix + gettext("lodgement"),
                "lodgement{0}.id".format(part_id):
                    prefix + gettext("lodgement ID"),
                "lodgement{0}.group_id".format(part_id):
                    prefix + gettext("lodgement group"),
                "lodgement{0}.title".format(part_id):
                    prefix + gettext("lodgement title"),
                "lodgement{0}.notes".format(part_id):
                    prefix + gettext("lodgement notes"),
                "lodgement_group{0}.id".format(part_id):
                    prefix + gettext("lodgement group ID"),
                "lodgement_group{0}.title".format(part_id):
                    prefix + gettext("lodgement group title"),
            })
            key = "lodgement{0}.xfield_{1}"
            titles.update({
                key.format(part_id, field['field_name']):
                    prefix + gettext("lodgement {field}").format(
                        field=field['field_name'])
                for field in lodge_fields.values()
            })
        if len(event['parts']) > 1:
            titles.update({
                ",".join("part{0}.status".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: registration status"),
                ",".join("part{0}.is_camping_mat".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: camping mat user"),
                ",".join("part{0}.lodgement_id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement"),
                ",".join("lodgement{0}.id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement ID"),
                ",".join("lodgement{0}.group_id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement group"),
                ",".join("lodgement{0}.title".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement title"),
                ",".join("lodgement{0}.notes".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement notes"),
                ",".join("lodgement_group{0}.id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement group ID"),
                ",".join("lodgement_group{0}.title".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement group title"),
            })
            key = "lodgement{0}.xfield_{1}"
            titles.update({
                ",".join(key.format(part_id, field['field_name'])
                         for part_id in event['parts']):
                    gettext("any part: lodgement {field}").format(
                        field=field['field_name'])
                for field in lodge_fields.values()
            })
        return choices, titles

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def registration_query(self, rs: RequestState, event_id: int,
                           download: Optional[str], is_search: bool
                           ) -> Response:
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        spec = self.make_registration_query_spec(rs.ambience['event'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
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
        choices, titles = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements, lodgement_groups,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = self.conf["DEFAULT_QUERIES_REGISTRATION"](
            rs.gettext, rs.ambience['event'], spec)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries,
            'titles': titles, 'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        scope = "qview_registration"
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "registration_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "registration_query", params)

    @staticmethod
    def make_course_query_spec(event: CdEDBObject) -> Dict[str, str]:
        """Helper to enrich ``QUERY_SPECS['qview_event_course']``.

        Since each event has custom course fields we have to amend the query
        spec on the fly.
        """
        tracks = event['tracks']
        course_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.course
        }

        # This is an OrderedDict, so order should be respected.
        spec = copy.deepcopy(QUERY_SPECS["qview_event_course"])
        spec.update({
            "course_fields.xfield_{0}".format(field['field_name']):
                const.FieldDatatypes(field['kind']).name
            for field in course_fields.values()
        })

        for track_id, track in tracks.items():
            spec["track{0}.is_offered".format(track_id)] = "bool"
            spec["track{0}.takes_place".format(track_id)] = "bool"
            spec["track{0}.attendees".format(track_id)] = "int"
            spec["track{0}.instructors".format(track_id)] = "int"
            for rank in range(track['num_choices']):
                spec["track{0}.num_choices{1}".format(track_id, rank)] = "int"

        return spec

    # TODO specify return type as OrderedDict.
    @staticmethod
    def make_course_query_aux(rs: RequestState, event: CdEDBObject,
                              courses: CdEDBObjectMap,
                              fixed_gettext: bool = False
                              ) -> Tuple[Dict[str, Dict[int, str]],
                                         Dict[str, str]]:
        """Un-inlined code to prepare input for template.

        :param fixed_gettext: whether or not to use a fixed translation
            function. True means static, False means localized.
        :returns: Choices for select inputs and titles for columns.
        """

        tracks = event['tracks']
        gettext = rs.default_gettext if fixed_gettext else rs.gettext

        # Construct choices.
        course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
        course_choices = OrderedDict(
            xsorted((c["id"], course_identifier(c)) for c in courses.values()))
        choices: Dict[str, Dict[int, str]] = {
            "course.course_id": course_choices
        }
        course_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.course
            }
        if not fixed_gettext:
            # Course fields value -> description
            choices.update({
                "course_fields.xfield_{0}".format(field['field_name']):
                    OrderedDict(field['entries'])
                for field in course_fields.values() if field['entries']
            })

        # Construct titles.
        titles: Dict[str, str] = {
            "course.id": gettext("course id"),
            "course.course_id": gettext("course"),
            "course.nr": gettext("course nr"),
            "course.title": gettext("course title"),
            "course.description": gettext("course description"),
            "course.shortname": gettext("course shortname"),
            "course.instructors": gettext("course instructors"),
            "course.min_size": gettext("course min size"),
            "course.max_size": gettext("course max size"),
            "course.notes": gettext("course notes"),
        }
        titles.update({
            "course_fields.xfield_{}".format(field['field_name']):
                field['field_name']
            for field in course_fields.values()
        })
        for track_id, track in tracks.items():
            if len(tracks) > 1:
                prefix = "{shortname}: ".format(shortname=track['shortname'])
            else:
                prefix = ""
            titles.update({
                "track{0}.takes_place".format(track_id):
                    prefix + gettext("takes place"),
                "track{0}.is_offered".format(track_id):
                    prefix + gettext("is offered"),
                "track{0}.attendees".format(track_id):
                    prefix + gettext("attendees"),
                "track{0}.instructors".format(track_id):
                    prefix + gettext("instructors"),
            })
            for rank in range(track['num_choices']):
                titles.update({
                    "track{0}.num_choices{1}".format(track_id, rank):
                        prefix + gettext("{}. choices").format(
                            rank+1),
                })

        return choices, titles

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def course_query(self, rs: RequestState, event_id: int,
                     download: Optional[str], is_search: bool) -> Response:

        spec = self.make_course_query_spec(rs.ambience['event'])
        query_input = mangle_query_input(rs, spec)
        query: Optional[Query] = None
        if is_search:
            query = check(rs, vtypes.QueryInput,
                query_input, "query", spec=spec, allow_empty=False)

        course_ids = self.eventproxy.list_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        choices, titles = self.make_course_query_aux(
            rs, rs.ambience['event'], courses,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        tracks = rs.ambience['event']['tracks']
        selection_default = ["course.shortname", ]
        for col in ("is_offered", "takes_place", "attendees"):
            selection_default += list("track{}.{}".format(t_id, col)
                                      for t_id in tracks)

        default_queries = self.conf["DEFAULT_QUERIES_COURSE"](
            rs.gettext, rs.ambience['event'], spec)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries,
            'titles': titles, 'selection_default': selection_default,
        }

        scope = "qview_event_course"
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "course_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "course_query", params)

    @staticmethod
    def make_lodgement_query_spec(event: CdEDBObject) -> Dict[str, str]:
        parts = event["parts"]
        lodgement_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.lodgement
        }

        # This is an OrderedDcit, so order should be respected.
        spec = copy.deepcopy(QUERY_SPECS["qview_event_lodgement"])
        spec.update({
            f"lodgement_fields.xfield_{field['field_name']}":
                const.FieldDatatypes(field['kind']).name
            for field in lodgement_fields.values()
        })

        for part_id, part in parts.items():
            spec[f"part{part_id}.regular_inhabitants"] = "int"
            spec[f"part{part_id}.camping_mat_inhabitants"] = "int"
            spec[f"part{part_id}.total_inhabitants"] = "int"
            spec[f"part{part_id}.group_regular_inhabitants"] = "int"
            spec[f"part{part_id}.group_camping_mat_inhabitants"] = "int"
            spec[f"part{part_id}.group_total_inhabitants"] = "int"

        return spec

    @staticmethod
    def make_lodgement_query_aux(rs: RequestState, event: CdEDBObject,
                                 lodgements: CdEDBObjectMap,
                                 lodgement_groups: CdEDBObjectMap,
                                 fixed_gettext: bool = False
                                 ) -> Tuple[Dict[str, Dict[int, str]],
                                            Dict[str, str]]:
        """Un-inlined code to prepare input for template.

        :param fixed_gettext: whether or not to use a fixed translation
            function. True means static, False means localized.
        :returns: Choices for select inputs and titles for columns.
        """

        parts = event['parts']
        gettext = rs.default_gettext if fixed_gettext else rs.gettext

        # Construct choices.
        lodgement_choices = OrderedDict(
            (l_id, l['title'])
            for l_id, l in keydictsort_filter(lodgements,
                                              EntitySorter.lodgement))
        lodgement_group_choices = OrderedDict({-1: gettext(n_("--no group--"))})
        lodgement_group_choices.update(
            [(lg_id, lg['title']) for lg_id, lg in keydictsort_filter(
                lodgement_groups, EntitySorter.lodgement_group)])
        choices: Dict[str, Dict[int, str]] = {
            "lodgement.lodgement_id": lodgement_choices,
            "lodgement_group.id": lodgement_group_choices,
        }
        lodgement_fields = {
            field_id: field for field_id, field in event['fields'].items()
            if field['association'] == const.FieldAssociations.lodgement
        }
        if not fixed_gettext:
            # Lodgement fields value -> description
            choices.update({
                f"lodgement_fields.xfield_{field['field_name']}":
                    OrderedDict(field['entries'])
                for field in lodgement_fields.values() if field['entries']
            })

        # Construct titles.
        titles: Dict[str, str] = {
            "lodgement.id": gettext(n_("Lodgement ID")),
            "lodgement.lodgement_id": gettext(n_("Lodgement")),
            "lodgement.title": gettext(n_("Title_[[name of an entity]]")),
            "lodgement.regular_capacity": gettext(n_("Regular Capacity")),
            "lodgement.camping_mat_capacity":
                gettext(n_("Camping Mat Capacity")),
            "lodgement.notes": gettext(n_("Lodgement Notes")),
            "lodgement.group_id": gettext(n_("Lodgement Group ID")),
            "lodgement_group.tmp_id": gettext(n_("Lodgement Group")),
            "lodgement_group.title": gettext(n_("Lodgement Group Title")),
            "lodgement_group.regular_capacity":
                gettext(n_("Lodgement Group Regular Capacity")),
            "lodgement_group.camping_mat_capacity":
                gettext(n_("Lodgement Group Camping Mat Capacity")),
        }
        titles.update({
            f"lodgement_fields.xfield_{field['field_name']}":
                field['field_name']
            for field in lodgement_fields.values()
        })
        for part_id, part in parts.items():
            if len(parts) > 1:
                prefix = f"{part['shortname']}: "
            else:
                prefix = ""
            titles.update({
                f"part{part_id}.regular_inhabitants":
                    prefix + gettext(n_("Regular Inhabitants")),
                f"part{part_id}.camping_mat_inhabitants":
                    prefix + gettext(n_("Reserve Inhabitants")),
                f"part{part_id}.total_inhabitants":
                    prefix + gettext(n_("Total Inhabitants")),
                f"part{part_id}.group_regular_inhabitants":
                    prefix + gettext(n_("Group Regular Inhabitants")),
                f"part{part_id}.group_camping_mat_inhabitants":
                    prefix + gettext(n_("Group Reserve Inhabitants")),
                f"part{part_id}.group_total_inhabitants":
                    prefix + gettext(n_("Group Total Inhabitants")),
            })

        return choices, titles

    @access("event")
    @event_guard()
    @REQUESTdata("download", "is_search")
    def lodgement_query(self, rs: RequestState, event_id: int,
                        download: Optional[str], is_search: bool) -> Response:

        spec = self.make_lodgement_query_spec(rs.ambience['event'])
        query_input = mangle_query_input(rs, spec)
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
        choices, titles = self.make_lodgement_query_aux(
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
        default_queries: List[Query] = []

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'defualt_queries': default_queries,
            'titles': titles, 'selection_default': selection_default,
        }

        scope = "qview_event_lodgement"
        if not rs.has_validation_errors() and is_search and query:
            query.scope = scope
            params['result'] = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            return self._send_query_result(
                rs, download, "lodgement_result", scope, query, params)
        else:
            rs.values['is_search'] = is_search = False
            return self.render(rs, "lodgement_query", params)

    def _send_query_result(self, rs: RequestState, download: Optional[str],
                           filename: str, scope: str, query: Query,
                           params: CdEDBObject) -> Response:
        if download:
            shortname = rs.ambience['event']['shortname']
            return self.send_query_download(
                rs, params['result'], query.fields_of_interest, kind=download,
                filename=f"{shortname}_{filename}",
                substitutions=params['choices'])
        else:
            if scope == "qview_registration":
                page = "registration_query"
            elif scope == "qview_event_course":
                page = "course_query"
            elif scope == "qview_event_lodgement":
                page = "lodgement_query"
            else:
                raise RuntimeError(n_("Unknown query scope."))
            return self.render(rs, page, params)

    @access("event")
    @event_guard(check_offline=True)
    def checkin_form(self, rs: RequestState, event_id: int) -> Response:
        """Render form."""
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        there = lambda registration, part_id: const.RegistrationPartStati(
            registration['parts'][part_id]['status']).is_present()
        registrations = {
            k: v
            for k, v in registrations.items()
            if (not v['checkin']
                and any(there(v, id) for id in rs.ambience['event']['parts']))}
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event']['begin'])
        reg_order = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        registrations = OrderedDict(
            (reg_id, registrations[reg_id]) for reg_id in reg_order)
        return self.render(rs, "checkin", {
            'registrations': registrations, 'personas': personas,
            'lodgements': lodgements})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("registration_id")
    def checkin(self, rs: RequestState, event_id: int, registration_id: vtypes.ID
                ) -> Response:
        """Check a participant in."""
        if rs.has_validation_errors():
            return self.checkin_form(rs, event_id)
        registration = self.eventproxy.get_registration(rs, registration_id)
        if registration['event_id'] != event_id:
            raise werkzeug.exceptions.NotFound(n_("Wrong associated event."))
        if registration['checkin']:
            rs.notify("warning", n_("Already checked in."))
            return self.checkin_form(rs, event_id)

        new_reg = {
            'id': registration_id,
            'checkin': now(),
        }
        code = self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, 'event/checkin')

    FIELD_REDIRECT = {
        const.FieldAssociations.registration: "event/registration_query",
        const.FieldAssociations.course: "event/course_query",
        const.FieldAssociations.lodgement: "event/lodgement_query",
    }

    def field_set_aux(self, rs: RequestState, event_id: int, field_id: Optional[int],
                      ids: Collection[int], kind: const.FieldAssociations) \
            -> Tuple[CdEDBObjectMap, List[int], Dict[int, str], Optional[CdEDBObject]]:
        """Process field set inputs.

        This function retrieves the data dependent on the given kind and returns it in
        a standardized way to be used in the generic field_set_* functions.

        :param ids: ids of the entities where the field should be modified.
        :param kind: specifies the entity: registration, course or lodgement

        :returns: A tuple of values, containing
            * entities: corresponding to the given ids (registrations, courses, lodgements)
            * ordered_ids: given ids, sorted by the corresponding EntitySorter
            * labels: name of the entities which will be displayed in the template
            * field: the event field which will be changed, None if no field_id was given
        """
        if kind == const.FieldAssociations.registration:
            if not ids:
                ids = self.eventproxy.list_registrations(rs, event_id)
            entities = self.eventproxy.get_registrations(rs, ids)
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in entities.values()))
            labels = {
                reg_id: (f"{personas[entity['persona_id']]['given_names']}"
                         f" {personas[entity['persona_id']]['family_name']}")
                for reg_id, entity in entities.items()}
            ordered_ids = xsorted(
                entities.keys(), key=lambda anid: EntitySorter.persona(
                    personas[entities[anid]['persona_id']]))
        elif kind == const.FieldAssociations.course:
            if not ids:
                ids = self.eventproxy.list_courses(rs, event_id)
            entities = self.eventproxy.get_courses(rs, ids)
            labels = {course_id: f"{course['nr']} {course['shortname']}"
                      for course_id, course in entities.items()}
            ordered_ids = xsorted(
                entities.keys(), key=lambda anid: EntitySorter.course(entities[anid]))
        elif kind == const.FieldAssociations.lodgement:
            if not ids:
                ids = self.eventproxy.list_lodgements(rs, event_id)
            entities = self.eventproxy.get_lodgements(rs, ids)
            group_ids = {lodgement['group_id'] for lodgement in entities.values()
                         if lodgement['group_id'] is not None}
            groups = self.eventproxy.get_lodgement_groups(rs, group_ids)
            labels = {
                lodg_id: f"{lodg['title']}" if lodg['group_id'] is None
                         else safe_filter(f"{lodg['title']}, "
                                          f"<em>{groups[lodg['group_id']]['title']}</em>")
                for lodg_id, lodg in entities.items()}
            ordered_ids = xsorted(
                entities.keys(), key=lambda anid: EntitySorter.lodgement(entities[anid]))
        else:
            # this should not happen, since we check before for validation errors
            raise NotImplementedError(f"Unknown kind {kind}")

        if field_id:
            if field_id not in rs.ambience['event']['fields']:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated event."))
            field = rs.ambience['event']['fields'][field_id]
            if field['association'] != kind:
                raise werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        else:
            field = None

        return entities, ordered_ids, labels, field

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind")
    def field_set_select(self, rs: RequestState, event_id: int,
                         field_id: Optional[vtypes.ID],
                         ids: Optional[vtypes.IntCSVList],
                         kind: const.FieldAssociations) -> Response:
        """Select a field for manipulation across multiple entities."""
        if rs.has_validation_errors():
            return self.render(rs, "field_set_select")
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        if field_id:
            return self.redirect(
                rs, "event/field_set_form", {
                    'ids': (','.join(str(i) for i in ids) if ids else None),
                    'field_id': field_id, 'kind': kind.value})
        _, ordered_ids, labels, _ = self.field_set_aux(rs, event_id, field_id, ids, kind)
        fields = [(field['id'], field['field_name'])
                  for field in xsorted(rs.ambience['event']['fields'].values(),
                                       key=EntitySorter.event_field)
                  if field['association'] == kind]
        return self.render(
            rs, "field_set_select", {
                'ids': (','.join(str(i) for i in ids) if ids else None),
                'ordered': ordered_ids, 'labels': labels, 'fields': fields,
                'kind': kind.value, 'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind")
    def field_set_form(self, rs: RequestState, event_id: int, field_id: vtypes.ID,
                       ids: Optional[vtypes.IntCSVList], kind: const.FieldAssociations,
                       internal: bool = False) -> Response:
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            redirect = self.FIELD_REDIRECT.get(kind, "event/show_event")
            return self.redirect(rs, redirect)
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        entities, ordered_ids, labels, field = self.field_set_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        values = {f"input{anid}": entity['fields'].get(field['field_name'])
                  for anid, entity in entities.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "field_set", {
            'ids': (','.join(str(i) for i in ids) if ids else None),
            'entities': entities, 'labels': labels, 'ordered': ordered_ids,
            'kind': kind.value, 'cancellink': self.FIELD_REDIRECT[kind]})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("field_id", "ids", "kind")
    def field_set(self, rs: RequestState, event_id: int, field_id: vtypes.ID,
                  ids: Optional[vtypes.IntCSVList],
                  kind: const.FieldAssociations) -> Response:
        """Modify a specific field on the given entities."""
        if rs.has_validation_errors():
            return self.field_set_form(  # type: ignore
                rs, event_id, kind=kind, internal=True)
        if ids is None:
            ids = cast(vtypes.IntCSVList, [])

        entities, _, _, field = self.field_set_aux(
            rs, event_id, field_id, ids, kind)
        assert field is not None  # to make mypy happy

        data_params: TypeMapping = {
            f"input{anid}": Optional[  # type: ignore
                VALIDATOR_LOOKUP[const.FieldDatatypes(field['kind']).name]]
            for anid in entities
        }
        data = request_extractor(rs, data_params)
        if rs.has_validation_errors():
            return self.field_set_form(  # type: ignore
                rs, event_id, kind=kind, internal=True)

        if kind == const.FieldAssociations.registration:
            entity_setter: EntitySetter = self.eventproxy.set_registration
        elif kind == const.FieldAssociations.course:
            entity_setter = self.eventproxy.set_course
        elif kind == const.FieldAssociations.lodgement:
            entity_setter = self.eventproxy.set_lodgement
        else:
            # this can not happen, since kind was validated successfully
            raise NotImplementedError(f"Unknown kind {kind}.")

        code = 1
        for anid, entity in entities.items():
            if data[f"input{anid}"] != entity['fields'].get(field['field_name']):
                new = {
                    'id': anid,
                    'fields': {field['field_name']: data[f"input{anid}"]}
                }
                code *= entity_setter(rs, new)
        self.notify_return_code(rs, code)

        if kind == const.FieldAssociations.registration:
            query = Query(
                "qview_registration",
                self.make_registration_query_spec(rs.ambience['event']),
                ("persona.given_names", "persona.family_name", "persona.username",
                 "reg.id", f"reg_fields.xfield_{field['field_name']}"),
                (("reg.id", QueryOperators.oneof, entities),),
                (("persona.family_name", True), ("persona.given_names", True))
            )
        elif kind == const.FieldAssociations.course:
            query = Query(
                "qview_event_course",
                self.make_course_query_spec(rs.ambience['event']),
                ("course.nr", "course.shortname", "course.title", "course.id",
                 f"course_fields.xfield_{field['field_name']}"),
                (("course.id", QueryOperators.oneof, entities),),
                (("course.nr", True), ("course.shortname", True))
            )
        elif kind == const.FieldAssociations.lodgement:
            query = Query(
                "qview_event_lodgement",
                self.make_lodgement_query_spec(rs.ambience['event']),
                ("lodgement.title", "lodgement_group.title", "lodgement.id",
                 f"lodgement_fields.xfield_{field['field_name']}"),
                (("lodgement.id", QueryOperators.oneof, entities),),
                (("lodgement.title", True), ("lodgement.id", True))
            )
        else:
            # this can not happen, since kind was validated successfully
            raise NotImplementedError(f"Unknown kind {kind}.")

        redirect = self.FIELD_REDIRECT[kind]
        return self.redirect(rs, redirect, querytoparams_filter(query))

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs: RequestState, event_id: int) -> Response:
        """Lock an event for offline usage."""
        code = self.eventproxy.lock_event(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard()
    @REQUESTfile("json")
    def unlock_event(self, rs: RequestState, event_id: int,
                     json: werkzeug.datastructures.FileStorage) -> Response:
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        data = check(rs, vtypes.SerializedEventUpload, json)
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        assert data is not None
        if event_id != data['id']:
            rs.notify("error", n_("Data from wrong event."))
            return self.show_event(rs, event_id)
        # Check for unmigrated personas
        current = self.eventproxy.export_event(rs, event_id)
        claimed = {e['persona_id'] for e in data['event.registrations'].values()
                   if not e['real_persona_id']}
        if claimed - set(current['core.personas']):
            rs.notify("error", n_("There exist unmigrated personas."))
            return self.show_event(rs, event_id)

        code = self.eventproxy.unlock_import_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_archive", "create_past_event")
    def archive_event(self, rs: RequestState, event_id: int, ack_archive: bool,
                      create_past_event: bool) -> Response:
        """Archive an event and optionally create a past event.

        This is at the boundary between event and cde frontend, since
        the past-event stuff generally resides in the cde realm.
        """
        if rs.ambience['event']['is_archived']:
            rs.notify("warning", n_("Event already archived."))
            return self.redirect(rs, "event/show_event")
        if not ack_archive:
            rs.append_validation_error(
                ("ack_archive", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if rs.ambience['event']['end'] >= now().date():
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        new_ids, message = self.pasteventproxy.archive_event(
            rs, event_id, create_past_event=create_past_event)
        if message:
            rs.notify("warning", message)
            return self.redirect(rs, "event/show_event")
        rs.notify("success", n_("Event archived."))
        if new_ids is None:
            return self.redirect(rs, "event/show_event")
        elif len(new_ids) == 1:
            rs.notify("info", n_("Created past event."))
            return self.redirect(rs, "cde/show_past_event",
                                 {'pevent_id': unwrap(new_ids)})
        else:
            rs.notify("info", n_("Created multiple past events."))
            return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata("ack_delete")
    def delete_event(self, rs: RequestState, event_id: int, ack_delete: bool
                     ) -> Response:
        """Remove an event."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        if rs.ambience['event']['end'] >= now().date():
            rs.notify("error", n_("Event is not concluded yet."))
            return self.redirect(rs, "event/show_event")

        blockers = self.eventproxy.delete_event_blockers(rs, event_id)
        cascade = {"registrations", "courses", "lodgement_groups", "lodgements",
                   "field_definitions", "course_tracks", "event_parts", "orgas",
                   "questionnaire", "log", "mailinglists"} & blockers.keys()

        code = self.eventproxy.delete_event(rs, event_id, cascade)
        if not code:
            return self.show_event(rs, event_id)
        else:
            rs.notify("success", n_("Event deleted."))
            return self.redirect(rs, "event/index")

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

        anid, errs = validate_check(vtypes.ID, phrase, argname="phrase")
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
                _, errs = validate_check(vtypes.NonRegex, t, argname="phrase")
                if errs:
                    valid = False
            if not valid:
                data = []
            else:
                search = [("username,family_name,given_names,display_name",
                           QueryOperators.match, t) for t in terms]
                search.extend(search_additions)
                spec = copy.deepcopy(QUERY_SPECS["qview_quick_registration"])
                spec["username,family_name,given_names,display_name"] = "str"
                spec.update(spec_additions)
                query = Query(
                    "qview_quick_registration", spec,
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

    @access("event")
    @event_guard()
    @REQUESTdata("phrase")
    def quick_show_registration(self, rs: RequestState, event_id: int,
                                phrase: str) -> Response:
        """Allow orgas to quickly retrieve a registration.

        The search phrase may be anything: a numeric id or a string
        matching the data set.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        anid, errs = validate_check(vtypes.CdedbID, phrase, argname="phrase")
        if not errs:
            reg_ids = self.eventproxy.list_registrations(
                rs, event_id, persona_id=anid)
            if reg_ids:
                reg_id = unwrap(reg_ids.keys())
                return self.redirect(rs, "event/show_registration",
                                     {'registration_id': reg_id})

        anid, errs = validate_check(vtypes.ID, phrase, argname="phrase")
        if not errs:
            assert anid is not None
            regs = self.eventproxy.get_registrations(rs, (anid,))
            if regs:
                reg = unwrap(regs)
                if reg['event_id'] == event_id:
                    return self.redirect(rs, "event/show_registration",
                                         {'registration_id': reg['id']})

        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        valid = True
        for t in terms:
            _, errs = validate_check(vtypes.NonRegex, t, argname="phrase")
            if errs:
                valid = False
        if not valid:
            rs.notify("warning", n_("Active characters found in search."))
            return self.show_event(rs, event_id)

        search = [("username,family_name,given_names,display_name",
                   QueryOperators.match, t) for t in terms]
        spec = copy.deepcopy(QUERY_SPECS["qview_quick_registration"])
        spec["username,family_name,given_names,display_name"] = "str"
        query = Query(
            "qview_quick_registration", spec,
            ("registrations.id", "username", "family_name",
             "given_names", "display_name"),
            search, (("registrations.id", True),))
        result = self.eventproxy.submit_general_query(
            rs, query, event_id=event_id)
        if len(result) == 1:
            return self.redirect(rs, "event/show_registration",
                                 {'registration_id': result[0]['id']})
        elif result:
            # TODO make this accessible
            pass
        base_query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"],
            [],
            (("persona.family_name", True), ("persona.given_names", True))
        )
        regex = "({})".format("|".join(terms))
        given_names_constraint = (
            'persona.given_names', QueryOperators.regex, regex)
        family_name_constraint = (
            'persona.family_name', QueryOperators.regex, regex)

        for effective in ([given_names_constraint, family_name_constraint],
                          [given_names_constraint],
                          [family_name_constraint]):
            query = copy.deepcopy(base_query)
            query.constraints.extend(effective)
            result = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            if len(result) == 1:
                return self.redirect(rs, "event/show_registration",
                                     {'registration_id': result[0]['id']})
            elif result:
                params = querytoparams_filter(query)
                return self.redirect(rs, "event/registration_query",
                                     params)
        rs.notify("warning", n_("No registration found."))
        return self.show_event(rs, event_id)

    @access("event_admin")
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
        registration_map = self.eventproxy.get_registration_map(rs, event_ids)
        events = self.eventproxy.get_events(rs, event_ids)
        all_events = self.eventproxy.list_events(rs)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_log", {
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
        return self.render(rs, "view_event_log", {
            'log': log, 'total': total, 'length': _length, 'personas': personas,
            'registration_map': registration_map, 'loglinks': loglinks})
