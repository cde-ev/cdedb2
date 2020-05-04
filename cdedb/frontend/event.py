#!/usr/bin/env python3

"""Services for the event realm."""

import cgitb
from collections import OrderedDict, Counter
import collections.abc
import copy
import csv
import decimal
import functools
import hashlib
import itertools
import json
import operator
import pathlib
import re
import subprocess
import sys
import tempfile
import datetime

import magic
import psycopg2.extensions
import werkzeug.exceptions
from werkzeug import Response
from typing import Sequence, Dict, Any, Collection, Mapping, List

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, csv_output,
    check_validation as check, event_guard, query_result_to_json,
    REQUESTfile, request_extractor, cdedbid_filter, querytoparams_filter,
    xdictsort_filter, enum_entries_filter, safe_filter, cdedburl,
    CustomCSVDialect, keydictsort_filter, calculate_db_logparams,
    calculate_loglinks, process_dynamic_input)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input, Query
from cdedb.common import (
    n_, merge_dicts, determine_age_class, deduct_years, AgeClasses,
    unwrap, now, json_serialize, glue, CourseChoiceToolActions,
    CourseFilterPositions, diacritic_patterns, shutil_copy, PartialImportError,
    DEFAULT_NUM_COURSE_CHOICES, mixed_existence_sorter, EntitySorter,
    LodgementsSortkeys, xsorted, RequestState)
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import cdedb.validation as validate
import cdedb.ml_type_aux as ml_type


class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_event_user,
    }

    def render(self, rs, templatename, params=None):
        params = params or {}
        if 'event' in rs.ambience:
            params['is_locked'] = self.is_locked(rs.ambience['event'])
            if rs.user.persona_id:
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
            if (rs.ambience['event'].get('is_archived') and
                    rs.ambience['event'].get('is_cancelled')):
                rs.notify("info",
                    n_("This event was cancelled and has been archived."))
            elif rs.ambience['event'].get('is_archived'):
                rs.notify("info", n_("This event has been archived."))
            elif rs.ambience['event'].get('is_cancelled'):
                rs.notify("info", n_("This event has been cancelled."))
        return super().render(rs, templatename, params=params)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def is_locked(self, event):
        """Shorthand to determine locking state of an event.

        :type event: {str: object}
        :rtype: bool
        """
        return event['offline_lock'] != self.conf["CDEDB_OFFLINE_DEPLOYMENT"]

    @staticmethod
    def event_has_field(event, field_name, association):
        """Shorthand to check whether a field with given name and
        association is defined for an event.

        :type event: {str: object}
        :type field_name: str
        :type association: cdedb.constants.FieldAssociations
        :rtype: bool
        """
        return any((field['field_name'] == field_name
                    and field['association'] == field_name)
                   for field in event['fields'].values())

    @staticmethod
    def event_has_tracks(event):
        """Shorthand to check whether an event has course tracks.

        :type event: {str: object}
        :rtype: bool
        """
        return any(part['tracks'] for part in event['parts'].values())

    @access("anonymous")
    def index(self, rs):
        """Render start page."""
        open_event_list = self.eventproxy.list_db_events(
            rs, visible=True, current=True, archived=False)
        other_event_list = self.eventproxy.list_db_events(
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

    @access("event_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("event_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "gender", "birthday", "username", "telephone",
        "mobile", "address", "address_supplement", "postal_code",
        "location", "country", "notes")
    def create_user(self, rs, data):
        defaults = {
            'is_cde_realm': False,
            'is_event_realm': True,
            'is_ml_realm': True,
            'is_assembly_realm': False,
            'is_active': True,
        }
        data.update(defaults)
        return super().create_user(rs, data)

    @access("event_admin")
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    def user_search(self, rs, download, is_search):
        """Perform search."""
        spec = copy.deepcopy(QUERY_SPECS['qview_event_user'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {
            'pevent_id': OrderedDict(
                sorted(events.items(), key=operator.itemgetter(0))),
            'gender': OrderedDict(
                enum_entries_filter(
                    const.Genders,
                    rs.gettext if download is None else rs.default_gettext))
        }
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf["DEFAULT_QUERIES"]['qview_event_user']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search:
            query.scope = "qview_event_user"
            result = self.eventproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="user_search_result.csv")
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="user_search_result.json")
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("event_admin")
    def list_db_events(self, rs):
        """List all events organized via DB."""
        events = self.eventproxy.list_db_events(rs)
        events = self.eventproxy.get_events(rs, events.keys())
        for event in events.values():
            regs = self.eventproxy.list_registrations(rs, event['id'])
            event['registrations'] = len(regs)
        return self.render(rs, "list_db_events", {'events': events})

    @access("anonymous")
    def show_event(self, rs, event_id):
        """Display event organized via DB."""
        params = {}
        if "event" in rs.user.roles:
            params['orgas'] = OrderedDict(
                (e['id'], e) for e in xsorted(
                    self.coreproxy.get_personas(
                        rs, rs.ambience['event']['orgas']).values(),
                    key=EntitySorter.persona))
        if "ml" in rs.user.roles:
            ml_data = self._get_mailinglist_setter(rs.ambience['event'])
            params['participant_list'] = self.mlproxy.verify_existence(
                rs, ml_type.full_address(ml_data))
        if event_id in rs.user.orga or self.is_admin(rs):
            params['institutions'] = self.pasteventproxy.list_institutions(rs)
            params['minor_form_present'] = (self.conf["STORAGE_DIR"] / 'minor_form'
                                            / str(event_id)).exists()
        elif not rs.ambience['event']['is_visible']:
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        return self.render(rs, "show_event", params)

    @access("anonymous")
    def course_list(self, rs, event_id):
        """List courses from an event."""
        if (not rs.ambience['event']['is_course_list_visible']
                and not (event_id in rs.user.orga or self.is_admin(rs))):
            rs.notify("warning", n_("Course list not published yet."))
            return self.redirect(rs, "event/show_event")
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = None
        if course_ids:
            courses = self.eventproxy.get_courses(rs, course_ids.keys())
        return self.render(rs, "course_list", {'courses': courses})

    @access("event")
    @REQUESTdata(("part_id", "id_or_None"),
                 ("sortkey", "str_or_None"),
                 ("reverse", "bool"))
    def participant_list(self, rs, event_id, part_id=None, sortkey=None,
                         reverse=False):
        """List participants of an event"""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")
        if not (event_id in rs.user.orga or self.is_admin(rs)):
            reg_list = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id)
            if not reg_list:
                rs.notify("warning", n_("Not registered for event."))
                return self.redirect(rs, "event/show_event")
            registration_id = unwrap(reg_list.keys())
            registration = self.eventproxy.get_registration(rs, registration_id)
            parts = registration['parts']
            list_consent = registration['list_consent']
            if all(parts[part]['status'] != const.RegistrationPartStati.participant
                    for part in parts):
                rs.notify("warning", n_("No participant of event."))
                return self.redirect(rs, "event/show_event")
            if not rs.ambience['event']['is_participant_list_visible']:
                rs.notify("error", n_("Participant list not published yet."))
                return self.redirect(rs, "event/show_event")
        else:
            list_consent = True

        if part_id:
            part_ids = [part_id]
        else:
            part_ids = None

        data = self._get_participant_list_data(rs, event_id, part_ids, sortkey,
                                               reverse=reverse)
        if data is None:
            return self.redirect(rs, "event/participant_list")
        if len(rs.ambience['event']['parts']) == 1:
            part_id = list(rs.ambience['event']['parts'])[0]
        data['part_id'] = part_id
        data['list_consent'] = list_consent
        data['last_sortkey'] = sortkey
        data['last_reverse'] = reverse
        return self.render(rs, "participant_list", data)

    def _get_participant_list_data(
            self, rs, event_id, part_ids=None,
            sortkey=EntitySorter.given_names, reverse=False):
        """This provides data for download and online participant list.

        This is un-inlined so download_participant_list can use this
        as well."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
        }

        def sort_rank(sortkey, anid):
            prim_sorter = all_sortkeys.get(sortkey, EntitySorter.persona)
            sec_sorter = EntitySorter.persona
            if sortkey == "course":
                if not len(part_ids) == 1:
                    raise werkzeug.exceptions.BadRequest(n_(
                        "Only one part id."))
                part_id = unwrap(part_ids)
                all_tracks = parts[part_id]['tracks']
                registered_tracks = [registrations[anid]['tracks'][track_id]
                                     for track_id in all_tracks]
                tracks = xsorted(
                    registered_tracks,
                    key=lambda track: all_tracks[track['track_id']]['sortkey'])
                prim_keys = [track['course_id'] for track in tracks]
                prim_rank = [
                    prim_sorter(courses[prim_key]) if prim_key else ("0",)
                    for prim_key in prim_keys]
            else:
                prim_key = personas[registrations[anid]['persona_id']]
                prim_rank = [prim_sorter(prim_key)]
            sec_key = personas[registrations[anid]['persona_id']]
            sec_rank = sec_sorter(sec_key)
            return (*prim_rank, sec_rank)

        ordered = xsorted(registrations.keys(), reverse=reverse,
                          key=lambda anid: sort_rank(sortkey, anid))
        return {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'ordered': ordered, 'parts': parts,
        }

    @access("event")
    @event_guard()
    def change_event_form(self, rs, event_id):
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        merge_dicts(rs.values, rs.ambience['event'])
        return self.render(rs, "change_event",
                           {'institutions': institutions,
                            'accounts': self.conf["EVENT_BANK_ACCOUNTS"]})

    @access("event", modi={"POST"})
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "orga_address", "registration_text",
        "mail_text", "use_additional_questionnaire", "notes", "lodge_field",
        "reserve_field", "is_visible", "is_course_list_visible",
        "is_course_state_visible", "is_participant_list_visible",
        "courses_in_participant_list", "is_cancelled", "course_room_field",
        "nonmember_surcharge")
    @event_guard(check_offline=True)
    def change_event(self, rs, event_id, data):
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, "event", data)
        if rs.has_validation_errors():
            return self.change_event_form(rs, event_id)
        code = self.eventproxy.set_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    def get_minor_form(self, rs, event_id):
        """Retrieve minor form."""
        if not (rs.ambience['event']['is_visible']
                or event_id in rs.user.orga
                or self.is_admin(rs)):
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        path = self.conf["STORAGE_DIR"] / "minor_form" / str(event_id)
        return self.send_file(
            rs, mimetype="application/pdf",
            filename="{}_minor_form.pdf".format(
                rs.ambience['event']['shortname']),
            path=path)

    @access("event", modi={"POST"})
    @REQUESTfile("minor_form")
    @REQUESTdata(("delete", "bool"))
    @event_guard(check_offline=True)
    def change_minor_form(self, rs, event_id, minor_form, delete):
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check(rs, 'pdffile_or_None', minor_form, "minor_form")
        if not minor_form and not delete:
            rs.append_validation_error(
                ("minor_form", ValueError(n_("Mustn't be empty."))))
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        path = self.conf["STORAGE_DIR"] / 'minor_form' / str(event_id)
        if delete and not minor_form:
            if path.exists():
                path.unlink()
                rs.notify("success", n_("Minor form has been removed."))
            else:
                rs.notify("info", n_("Nothing to remove."))
        elif minor_form:
            with open(str(path), 'wb') as f:
                f.write(minor_form)
            rs.notify("success", n_("Minor form updated."))
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("orga_id", "cdedbid"))
    @event_guard(check_offline=True)
    def add_orga(self, rs, event_id, orga_id):
        """Make an additional persona become orga."""
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        new = {
            'id': event_id,
            'orgas': rs.ambience['event']['orgas'] | {orga_id}
        }
        code = self.eventproxy.set_event(rs, new)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("orga_id", "id"))
    @event_guard(check_offline=True)
    def remove_orga(self, rs, event_id, orga_id):
        """Demote a persona.

        This can drop your own orga role (but only if you're admin).
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
        new = {
            'id': event_id,
            'orgas': rs.ambience['event']['orgas'] - {orga_id}
        }
        code = self.eventproxy.set_event(rs, new)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("orgalist", "bool"))
    def create_event_mailinglist(self, rs, event_id, orgalist=False):
        """Create a default mailinglist for the event."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")

        ml_data = self._get_mailinglist_setter(rs.ambience['event'], orgalist)
        if not self.mlproxy.verify_existence(rs, ml_type.full_address(ml_data)):
            if not orgalist:
                link = cdedburl(rs, "event/register", {'event_id': event_id})
                ml_data['description'] = ml_data['description'].format(link)
            code = self.mlproxy.create_mailinglist(rs, ml_data)
            msg = (n_("Orga mailinglist created.") if orgalist
                   else n_("Participant mailinglist created."))
            self.notify_return_code(rs, code, success=msg)
            if code and orgalist:
                data = {
                    'id': event_id,
                    'orga_address': ml_type.full_address(ml_data),
                }
                self.eventproxy.set_event(rs, data)
        else:
            rs.notify("error", n_("Mailinglist %(address)s already exists."),
                      {'address': ml_type.full_address(ml_data)})
        return self.redirect(rs, "event/show_event")

    @access("event")
    @event_guard()
    def part_summary_form(self, rs, event_id):
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        current = {
            "{}_{}".format(key, part_id): value
            for part_id, part in rs.ambience['event']['parts'].items()
            for key, value in part.items() if key not in ('id', 'tracks')}
        for part_id, part in rs.ambience['event']['parts'].items():
            for track_id, track in part['tracks'].items():
                for k in ('title', 'shortname', 'num_choices', 'min_choices',
                          'sortkey'):
                    current["track_{}_{}_{}".format(k, part_id, track_id)] = \
                        track[k]
        for mod in rs.ambience['event']['fee_modifiers'].values():
            for k in ('modifier_name', 'amount', 'field_id'):
                current['fee_modifier_{}_{}_{}'.format(
                    k, mod['part_id'], mod['id'])] = mod[k]
        merge_dicts(rs.values, current)
        referenced_parts = set()
        referenced_tracks = set()
        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        for course in courses.values():
            referenced_tracks.update(course['segments'])
        # referenced tracks block part deletion
        for track_id in referenced_tracks:
            referenced_parts.add(tracks[track_id]['part_id'])

        fee_modifier_fields = [
            (field['id'], field['field_name'])
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.registration
            and field['kind'] == const.FieldDatatypes.bool
        ]
        fee_modifiers_by_part = {
            part_id: {
                e['id']: e
                for e in rs.ambience['event']['fee_modifiers'].values()
                if e['part_id'] == part_id
            }
            for part_id in rs.ambience['event']['parts']
        }
        return self.render(rs, "part_summary", {
            'fee_modifier_fields': fee_modifier_fields,
            'fee_modifiers_by_part': fee_modifiers_by_part,
            'referenced_parts': referenced_parts,
            'referenced_tracks': referenced_tracks,
            'has_registrations': has_registrations,
            'DEFAULT_NUM_COURSE_CHOICES': DEFAULT_NUM_COURSE_CHOICES})

    @staticmethod
    def process_part_input(rs, has_registrations):
        """This handles input to configure the parts.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type parts: {int: {str: object}}
        :param parts: parts to process
        :type has_registrations: bool
        :rtype: {int: {str: object}}
        """
        parts = rs.ambience['event']['parts']
        fee_modifiers = rs.ambience['event']['fee_modifiers']

        # Handle basic part data
        delete_flags = request_extractor(
            rs, (("delete_{}".format(part_id), "bool") for part_id in parts))
        deletes = {part_id for part_id in parts
                   if delete_flags['delete_{}'.format(part_id)]}
        if has_registrations and deletes:
            raise ValueError(n_("Registrations exist, no deletion."))
        spec = {
            'title': "str",
            'shortname': "str",
            'part_begin': "date",
            'part_end': "date",
            'fee': "decimal",
        }
        params = tuple(("{}_{}".format(key, part_id), value)
                       for part_id in parts if part_id not in deletes
                       for key, value in spec.items())
        data = request_extractor(rs, params)
        ret = {
            part_id: {key: data["{}_{}".format(key, part_id)] for key in spec}
            for part_id in parts if part_id not in deletes
        }

        def track_params(part_id, track_id):
            """
            Helper function to create the parameter extraction configuration
            for the data of a single track.
            """
            return (
                ("track_{}_{}_{}".format(k, part_id, track_id), t)
                for k, t in (('title', 'str'), ('shortname', 'str'),
                             ('num_choices', 'non_negative_int'),
                             ('min_choices', 'non_negative_int'),
                             ('sortkey', 'int')))

        def track_excavator(req_data, part_id, track_id):
            """
            Helper function to create a single track's data dict from the
            extracted request data.
            """
            return {
                k: req_data['track_{}_{}_{}'.format(k, part_id, track_id)]
                for k in ('title', 'shortname', 'num_choices', 'min_choices',
                          'sortkey')}

        # Handle newly created parts
        marker = 1
        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                if has_registrations:
                    raise ValueError(n_("Registrations exist, no creation."))
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_extractor(rs, params)
                ret[-marker] = {key: data["{}_-{}".format(key, marker)]
                                for key in spec}
            else:
                break
            marker += 1
        # Return index of last new row to template to generate all inputs
        # previously added by JS
        rs.values['create_last_index'] = marker - 1

        # Handle track data
        track_delete_flags = request_extractor(
            rs, (("track_delete_{}_{}".format(part_id, track_id), "bool")
                 for part_id, part in parts.items()
                 for track_id in part['tracks']))
        track_deletes = {
            track_id
            for part_id, part in parts.items() for track_id in part['tracks']
            if track_delete_flags['track_delete_{}_{}'.format(part_id,
                                                              track_id)]
        }
        if has_registrations and track_deletes:
            raise ValueError(n_("Registrations exist, no deletion."))
        params = tuple(itertools.chain.from_iterable(
            track_params(part_id, track_id)
            for part_id, part in parts.items()
            for track_id in part['tracks']
            if track_id not in track_deletes))

        def constraint_maker(part_id, track_id):
            min = "track_min_choices_{}_{}".format(part_id, track_id)
            num = "track_num_choices_{}_{}".format(part_id, track_id)
            msg = n_("Must be less or equal than total Course Choices.")
            return (lambda d: d[min] <= d[num], (min, ValueError(msg)))
        constraints = tuple(
            constraint_maker(part_id, track_id)
            for part_id, part in parts.items()
            for track_id in part['tracks']
            if track_id not in track_deletes)
        data = request_extractor(rs, params, constraints)
        rs.values['track_create_last_index'] = {}
        for part_id, part in parts.items():
            if part_id in deletes:
                continue
            ret[part_id]['tracks'] = {
                track_id: (track_excavator(data, part_id, track_id)
                           if track_id not in track_deletes else None)
                for track_id in part['tracks']}
            marker = 1
            while marker < 2 ** 5:
                will_create = unwrap(request_extractor(
                    rs,
                    (("track_create_{}_-{}".format(part_id, marker), "bool"),)))
                if will_create:
                    if has_registrations:
                        raise ValueError(
                            n_("Registrations exist, no creation."))
                    params = tuple(track_params(part_id, -marker))
                    constraints = (constraint_maker(part_id, -marker),)
                    newtrack = track_excavator(
                        request_extractor(rs, params, constraints),
                        part_id, -marker)
                    ret[part_id]['tracks'][-marker] = newtrack
                else:
                    break
                marker += 1
            rs.values['track_create_last_index'][part_id] = marker - 1

        # And now track data for newly created parts
        for new_part_id in range(1, rs.values['create_last_index'] + 1):
            ret[-new_part_id]['tracks'] = {}
            marker = 1
            while marker < 2 ** 5:
                will_create = unwrap(request_extractor(
                    rs,
                    (("track_create_-{}_-{}".format(new_part_id, marker),
                      "bool"),)))
                if will_create:
                    params = tuple(track_params(-new_part_id, -marker))
                    constraints = (constraint_maker(-new_part_id, -marker),)
                    newtrack = track_excavator(
                        request_extractor(rs, params, constraints),
                        -new_part_id, -marker)
                    ret[-new_part_id]['tracks'][-marker] = newtrack
                else:
                    break
                marker += 1
            rs.values['track_create_last_index'][-new_part_id] = marker - 1

        def fee_modifier_params(part_id, fee_modifier_id):
            """
            Helper function to create the parameter extraction configuration
            for the data of a single fee modifier.
            """
            return (
                ("fee_modifier_{}_{}_{}".format(k, part_id, fee_modifier_id), t)
                for k, t in (('modifier_name', 'restrictive_identifier'),
                             ('amount', 'decimal'),
                             ('field_id', 'id')))

        def fee_modifier_excavator(req_data, part_id, fee_modifier_id):
            """
            Helper function to create a single fee modifier's data dict from the
            extracted request data.
            """
            ret = {
                k: req_data['fee_modifier_{}_{}_{}'.format(
                    k, part_id, fee_modifier_id)]
                for k in ('modifier_name', 'amount', 'field_id')}
            ret['part_id'] = part_id
            if fee_modifier_id > 0:
                ret['id'] = fee_modifier_id
            return ret

        # Handle fee modifier data
        fee_modifier_delete_flags = request_extractor(
            rs, (("fee_modifier_delete_{}_{}".format(mod['part_id'], mod['id']),
                  "bool")
                 for mod in fee_modifiers.values()))
        fee_modifier_deletes = {
            mod['id']
            for mod in fee_modifiers.values()
            if fee_modifier_delete_flags['fee_modifier_delete_{}_{}'.format(
                mod['part_id'], mod['id'])]
        }
        if has_registrations and fee_modifier_deletes:
            raise ValueError(n_("Registrations exist, no deletion."))
        params = tuple(itertools.chain.from_iterable(
            fee_modifier_params(mod['part_id'], mod['id'])
            for mod in fee_modifiers.values()
            if mod['id'] not in fee_modifier_deletes))

        def constraint_maker(part_id, fee_modifier_id):
            key = "fee_modifier_field_id_{}_{}".format(part_id, fee_modifier_id)
            fields = rs.ambience['event']['fields']
            ret = [
                (lambda d: fields[d[key]]['association'] ==
                           const.FieldAssociations.registration,
                 (key, ValueError(n_(
                     "Fee Modifier linked to non-registration field.")))),
                (lambda d: fields[d[key]]['kind'] == const.FieldDatatypes.bool,
                 (key, ValueError(n_(
                     "Fee Modifier linked to non-bool field."))))
                ]
            return ret

        constraints = tuple(itertools.chain.from_iterable(
            constraint_maker(mod['part_id'], mod['id'])
            for mod in fee_modifiers.values()
            if mod['id'] not in fee_modifier_deletes))

        data = request_extractor(rs, params, constraints)
        rs.values['fee_modifier_create_last_index'] = {}
        ret_fee_modifiers = {
            mod['id']: (fee_modifier_excavator(data, mod['part_id'], mod['id'])
                        if mod['part_id'] not in deletes
                        and mod['id'] not in fee_modifier_deletes else None)
            for mod in fee_modifiers.values()}

        # Check for duplicate fields in the same part.
        field_msg = n_("Must not have multiple fee modifiers linked to the same"
                       " field in one event part.")
        name_msg = n_("Must not have multiple fee modifiers witht he same name "
                      "in one event part.")
        used_fields = {}
        used_names = {}
        if len(ret_fee_modifiers) == 1:
            f = unwrap(ret_fee_modifiers)
            used_fields[f['part_id']] = {f['field_id']}
            used_names[f['part_id']] = {f['modifier_name']}
        for e1, e2 in itertools.combinations(
                filter(None, ret_fee_modifiers.values()), 2):
            used_fields.setdefault(e1['part_id'], set()).add(e1['field_id'])
            used_fields.setdefault(e2['part_id'], set()).add(e2['field_id'])
            used_names.setdefault(e1['part_id'], set()).add(e1['modifier_name'])
            used_names.setdefault(e2['part_id'], set()).add(e2['modifier_name'])
            if e1['part_id'] == e2['part_id']:
                if e1['field_id'] == e2['field_id']:
                    base_key = "fee_modifier_field_id_{}_{}"
                    key1 = base_key.format(e1['part_id'], e1['id'])
                    rs.add_validation_error((key1, ValueError(field_msg)))
                    key2 = base_key.format(e2['part_id'], e2['id'])
                    rs.add_validation_error((key2, ValueError(field_msg)))
                if e1['modifier_name'] == e2['modifier_name']:
                    base_key = "fee_modifier_modifier_name_{}_{}"
                    key1 = base_key.format(e1['part_id'], e1['id'])
                    rs.add_validation_error((key1, ValueError(name_msg)))
                    key2 = base_key.format(e2['part_id'], e2['id'])
                    rs.add_validation_error((key2, ValueError(name_msg)))

        for part_id in parts:
            marker = 1
            while marker < 2 ** 5:
                will_create = unwrap(request_extractor(
                    rs, (("fee_modifier_create_{}_-{}".format(part_id, marker),
                          "bool"),)))
                if will_create:
                    if has_registrations:
                        raise ValueError(n_(
                            "Registrations exist, no creation."))
                    params = tuple(fee_modifier_params(part_id, -marker))
                    constraints = constraint_maker(part_id, -marker)
                    new_fee_modifier = fee_modifier_excavator(
                        request_extractor(rs, params, constraints),
                        part_id, -marker)
                    ret_fee_modifiers[-marker] = new_fee_modifier
                    if new_fee_modifier['field_id'] in used_fields.get(
                            part_id, set()):
                        rs.add_validation_error(
                            ("fee_modifier_field_id_{}_{}".format(
                                part_id, -marker),
                             ValueError(field_msg)))
                    if new_fee_modifier['modifier_name'] in used_names.get(
                            part_id, set()):
                        rs.add_validation_error(
                            ("fee_modifier_modifier_name_{}_{}".format(
                                part_id, -marker),
                             ValueError(name_msg)))
                    used_fields.setdefault(part_id, set()).add(
                        new_fee_modifier['field_id'])
                else:
                    break
                marker += 1
            rs.values['fee_modifier_create_last_index'][part_id] = marker - 1

        # Don't allow fee modifiers for newly created parts.

        # Handle deleted parts
        for part_id in deletes:
            ret[part_id] = None
        if not any(ret.values()):
            rs.append_validation_error(
                (None, ValueError(n_("At least one event part required."))))
            rs.notify("error", n_("At least one event part required."))
        return ret, ret_fee_modifiers

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def part_summary(self, rs, event_id):
        """Manipulate the parts of an event."""
        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        parts, fee_modifiers = self.process_part_input(rs, has_registrations)
        if rs.has_validation_errors():
            return self.part_summary_form(rs, event_id)
        for part_id, part in rs.ambience['event']['parts'].items():
            if parts.get(part_id) == part:
                # remove unchanged
                del parts[part_id]
        event = {
            'id': event_id,
            'parts': parts,
            'fee_modifiers': fee_modifiers,
        }
        code = self.eventproxy.set_event(rs, event)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/part_summary_form")

    @access("event")
    @event_guard()
    def field_summary_form(self, rs, event_id):
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
        for k, v in full_questionnaire.items():
            for row in v:
                if row['field_id']:
                    referenced.add(row['field_id'])
        if rs.ambience['event']['lodge_field']:
            referenced.add(rs.ambience['event']['lodge_field'])
        if rs.ambience['event']['reserve_field']:
            referenced.add(rs.ambience['event']['reserve_field'])
        if rs.ambience['event']['course_room_field']:
            referenced.add(rs.ambience['event']['course_room_field'])
        for mod in rs.ambience['event']['fee_modifiers'].values():
            referenced.add(mod['field_id'])
            fee_modifiers.add(mod['field_id'])
        return self.render(rs, "field_summary", {
            'referenced': referenced, 'fee_modifiers': fee_modifiers})

    @staticmethod
    def process_field_input(rs, fields):
        """This handles input to configure the fields.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type fields: {int: {str: object}}
        :param fields: ids of fields
        :rtype: {int: {str: object}}
        """
        delete_flags = request_extractor(
            rs, (("delete_{}".format(field_id), "bool") for field_id in fields))
        deletes = {field_id for field_id in fields
                   if delete_flags['delete_{}'.format(field_id)]}
        ret = {}
        params = lambda anid: (("kind_{}".format(anid), "enum_fielddatatypes"),
                               ("association_{}".format(anid),
                                "enum_fieldassociations"),
                               ("entries_{}".format(anid), "str_or_None"))
        for field_id in fields:
            if field_id not in deletes:
                tmp = request_extractor(rs, params(field_id))
                if rs.has_validation_errors():
                    break
                tmp = check(rs, "event_field", tmp,
                            extra_suffix="_{}".format(field_id))
                if tmp:
                    temp = {}
                    temp['kind'] = tmp["kind_{}".format(field_id)]
                    temp['association'] = tmp["association_{}".format(field_id)]
                    temp['entries'] = tmp["entries_{}".format(field_id)]
                    ret[field_id] = temp
        for field_id in deletes:
            ret[field_id] = None
        marker = 1
        params = lambda anid: (("field_name_-{}".format(anid), "str"),
                               ("kind_-{}".format(anid), "enum_fielddatatypes"),
                               ("association_-{}".format(anid),
                                "enum_fieldassociations"),
                               ("entries_-{}".format(anid), "str_or_None"))
        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                tmp = request_extractor(rs, params(marker))
                if rs.has_validation_errors():
                    marker += 1
                    break
                tmp = check(rs, "event_field", tmp, creation=True,
                            extra_suffix="_-{}".format(marker))
                if tmp:
                    temp = {}
                    temp['field_name'] = tmp["field_name_-{}".format(marker)]
                    temp['kind'] = tmp["kind_-{}".format(marker)]
                    temp['association'] = tmp["association_-{}".format(marker)]
                    temp['entries'] = tmp["entries_-{}".format(marker)]
                    ret[-marker] = temp
            else:
                break
            marker += 1
        count = Counter(
            field['field_name'] if field and 'field_name' in field
            else fields[f_id]['field_name']
            for f_id, field in ret.items())
        for field_id, field in ret.items():
            if field and 'field_name' in field and count[field['field_name']] > 1:
                rs.append_validation_error(
                    ("field_name_{}".format(field_id),
                      ValueError(n_("Field name not unique."))))
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata(('active_tab', 'str_or_None'))
    def field_summary(self, rs, event_id, active_tab):
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
        return self.redirect(rs, "event/field_summary_form",
                             anchor=(("tab:" + active_tab)
                                     if active_tab is not None else None))

    @staticmethod
    def _get_mailinglist_setter(event, orgalist=False):
        email_local_part = "{}{}".format(
            event['shortname'], "" if orgalist else "-all")
        # During event creation the id is not yet known.
        event_id = event.get('id')
        if orgalist:
            descr = ("Bitte wende dich bei Fragen oder Problemen, die mit "
                     "unserer Veranstaltung zusammenhängen, über diese Liste "
                     "an uns.")
            orga_ml_data = {
                'title': "{} Orgateam".format(event['title']),
                'local_part': email_local_part,
                'domain': const.MailinglistDomain.aka,
                'description': descr,
                'mod_policy': const.ModerationPolicy.unmoderated,
                'attachment_policy': const.AttachmentPolicy.allow,
                'subject_prefix': event['shortname'],
                'maxsize': 1024,
                'is_active': True,
                'event_id': event_id,
                'registration_stati': [],
                'assembly_id': None,
                'notes': None,
                'moderators': event['orgas'],
                'ml_type': const.MailinglistTypes.event_orga,
            }
            return orga_ml_data
        else:
            descr = ("Dieser Liste kannst du nur beitreten, indem du dich zu "
                     "unserer [Veranstaltung anmeldest]({}) und den Status "
                     "*Teilnehmer* erhälst. Auf dieser Liste stehen alle "
                     "Teilnehmer unserer Veranstaltung; sie kann im Vorfeld "
                     "zum Austausch untereinander genutzt werden.")
            participant_ml_data = {
                'title': "{} Teilnehmer".format(event['title']),
                'local_part': email_local_part,
                'domain': const.MailinglistDomain.aka,
                'description': descr,
                'mod_policy': const.ModerationPolicy.non_subscribers,
                'attachment_policy': const.AttachmentPolicy.pdf_only,
                'subject_prefix': event['shortname'],
                'maxsize': 1024,
                'is_active': True,
                'event_id': event_id,
                'registration_stati': [const.RegistrationPartStati.participant],
                'assembly_id': None,
                'notes': None,
                'moderators': event['orgas'],
                'ml_type': const.MailinglistTypes.event_associated,
            }
            return participant_ml_data

    @access("event_admin")
    def create_event_form(self, rs):
        """Render form."""
        institution_ids = self.pasteventproxy.list_institutions(rs).keys()
        institutions = self.pasteventproxy.get_institutions(rs, institution_ids)
        return self.render(rs, "create_event",
                           {'institutions': institutions,
                            'accounts': self.conf["EVENT_BANK_ACCOUNTS"]})

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("event_begin", "date"), ("event_end", "date"),
                 ("orga_ids", "str"), ("create_track", "bool"),
                 ("create_orga_list", "bool"),
                 ("create_participant_list", "bool"))
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "iban", "nonmember_surcharge", "notes")
    def create_event(self, rs, event_begin, event_end, orga_ids, data,
                     create_track, create_orga_list, create_participant_list):
        """Create a new event, organized via DB."""
        if orga_ids:
            data['orgas'] = {check(rs, "cdedbid", anid.strip(), "orga_ids")
                             for anid in orga_ids.split(",")}
        # multi part events will have to edit this later on
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
                'part_begin': event_begin,
                'part_end': event_end,
                'fee': decimal.Decimal(0),
                'tracks': ({-1: new_track} if create_track else {}),
            }
        }
        orga_ml_data = None
        orga_ml_address = None
        if create_orga_list:
            orga_ml_data = self._get_mailinglist_setter(data, orgalist=True)
            orga_ml_address = ml_type.full_address(orga_ml_data)
            data['orga_address'] = orga_ml_address
            if self.mlproxy.verify_existence(rs, orga_ml_address):
                orga_ml_data = None
                rs.notify("info", n_("Mailinglist %(address)s already exists."),
                          {'address': orga_ml_address})
        else:
            data['orga_address'] = None

        data = check(rs, "event", data, creation=True)
        if rs.has_validation_errors():
            return self.create_event_form(rs)
        new_id = self.eventproxy.create_event(rs, data)
        if orga_ml_data:
            orga_ml_data['event_id'] = new_id
            code = self.mlproxy.create_mailinglist(rs, orga_ml_data)
            self.notify_return_code(
                rs, code, success=n_("Orga mailinglist created."))
        if create_participant_list:
            participant_ml_data = self._get_mailinglist_setter(data)
            participant_ml_address = ml_type.full_address(participant_ml_data)
            if not self.mlproxy.verify_existence(rs, participant_ml_address):
                link = cdedburl(rs, "event/register", {'event_id': new_id})
                descr = participant_ml_data['description'].format(link)
                participant_ml_data['description'] = descr
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
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        params = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            all_registrations = self.eventproxy.get_registrations(
                rs, registration_ids)
            registrations = {
                k: v
                for k, v in all_registrations.items()
                if any(track['course_id'] == course_id
                       or track['course_instructor'] == course_id
                       for track in v['tracks'].values())
            }
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
            attendees = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas)
            params['personas'] = personas
            params['registrations'] = registrations
            params['attendees'] = attendees
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
    def change_course_form(self, rs, event_id, course_id):
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
    @REQUESTdata(("segments", "[int]"), ("active_segments", "[int]"))
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "max_size", "min_size", "notes")
    @event_guard(check_offline=True)
    def change_course(self, rs, event_id, course_id, segments, active_segments,
                      data):
        """Modify a course associated to an event organized via DB."""
        data['id'] = course_id
        data['segments'] = segments
        data['active_segments'] = active_segments
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(const.FieldDatatypes(field['kind']).name))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, "course", data)
        if rs.has_validation_errors():
            return self.change_course_form(rs, event_id, course_id)
        code = self.eventproxy.set_course(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @access("event")
    @event_guard(check_offline=True)
    def create_course_form(self, rs, event_id):
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
    @REQUESTdata(("segments", "[int]"))
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "max_size", "min_size", "notes")
    @event_guard(check_offline=True)
    def create_course(self, rs, event_id, segments, data):
        """Create a new course associated to an event organized via DB."""
        data['event_id'] = event_id
        data['segments'] = segments
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(const.FieldDatatypes(field['kind']).name))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, "course", data, creation=True)
        if rs.has_validation_errors():
            return self.create_course_form(rs, event_id)
        new_id = self.eventproxy.create_course(rs, data)
        self.notify_return_code(rs, new_id, success=n_("Course created."))
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    @event_guard(check_offline=True)
    def delete_course(self, rs, event_id, course_id, ack_delete):
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
    def stats(self, rs, event_id):
        """Present an overview of the basic stats."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        stati = const.RegistrationPartStati
        get_age = lambda u, p: determine_age_class(
            u['birthday'], rs.ambience['event']['parts'][p['part_id']]['part_begin'])

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
        per_part_statistics = OrderedDict()
        for key, test in tests1.items():
            per_part_statistics[key] = {
                part_id: sum(
                    1 for r in registrations.values()
                    if test(rs.ambience['event'], r, r['parts'][part_id]))
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
        per_track_statistics = OrderedDict()
        if tracks:
            # Additional dynamic tests for course attendee statistics
            for i in range(max(t['num_choices'] for t in tracks.values())):
                tests3[rs.gettext('In {}. Choice').format(i + 1)] = (
                    functools.partial(
                        lambda e, r, p, t, j: (
                            p['status'] == stati.participant
                            and t['course_id']
                            and len(t['choices']) > j
                            and (t['choices'][j] == t['course_id'])),
                        j=i))

            for key, test in tests2.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for c in courses.values()
                        if test(c, track_id))
                    for track_id in tracks}
            for key, test in tests3.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if test(rs.ambience['event'], r,
                                r['parts'][tracks[track_id]['part_id']],
                                r['tracks'][track_id]))
                    for track_id in tracks}

        # The base query object to use for links to event/registration_query
        base_query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ["reg.id", "persona.given_names", "persona.family_name",
             "persona.username"],
            [],
            (("persona.family_name", True), ("persona.given_names", True),)
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
        # Query filters for all the statistics defined and calculated above.
        # They are customized and inserted into the query on the fly by
        # get_query().
        # `e` is the event, `p` is the event_part, `t` is the track.
        query_filters = {
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
                 (deduct_years(p['part_begin'], 18) + datetime.timedelta(days=1),
                  deduct_years(p['part_begin'], 16)),),),
            ' u16': lambda e, p, t: (
                participant_filter(p),
                ("persona.birthday", QueryOperators.between,
                 (deduct_years(p['part_begin'], 16) + datetime.timedelta(days=1),
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
            'no course': lambda e, p, t: (
                participant_filter(p),
                ('course{}.id'.format(t['id']),
                 QueryOperators.empty, None),
                ('persona.id', QueryOperators.otherthan,
                 rs.ambience['event']['orgas']),)
        }
        query_additional_fields = {
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

        def get_query(category, part_id, track_id=None):
            if category not in query_filters:
                return None
            q = copy.deepcopy(base_query)
            e = rs.ambience['event']
            p = e['parts'][part_id]
            t = e['tracks'][track_id] if track_id else None
            for f in query_filters[category](e, p, t):
                q.constraints.append(f)
            if category in query_additional_fields:
                for f in query_additional_fields[category]:
                    q.fields_of_interest.append(f.format(track=track_id,
                                                         part=part_id))
            return q

        return self.render(rs, "stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_track_statistics': per_track_statistics,
            'get_query': get_query})

    @access("event")
    @event_guard()
    def course_assignment_checks(self, rs, event_id):
        """Provide some consistency checks for course assignment."""
        event = rs.ambience['event']
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
                    EntitySorter.persona(personas[registrations[problem[0]]['persona_id']]))

        return self.render(rs, "course_assignment_checks", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'course_problems': course_problems,
            'reg_problems': reg_problems})

    @access("event")
    @REQUESTdata(("course_id", "id_or_None"), ("track_id", "id_or_None"),
                 ("position", "infinite_enum_coursefilterpositions_or_None"),
                 ("ids", "int_csv_list_or_None"),
                 ("include_active", "bool_or_None"))
    @event_guard()
    def course_choices_form(self, rs, event_id, course_id, track_id, position,
                            ids, include_active):
        """Provide an overview of course choices.

        This allows flexible filtering of the displayed registrations.
        """
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
        stati = const.RegistrationPartStati

        if rs.has_validation_errors():
            registration_ids = all_reg_ids
            registrations = all_regs
            personas = self.coreproxy.get_personas(rs, (r['persona_id'] for r in
                                                        registrations.values()))
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
        for course_id, course in courses.items():
            for track_id in tracks:
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
    @REQUESTdata(("course_id", "id_or_None"), ("track_id", "id_or_None"),
                 ("position", "infinite_enum_coursefilterpositions_or_None"),
                 ("ids", "int_csv_list_or_None"),
                 ("include_active", "bool_or_None"),
                 ("registration_ids", "[int]"), ("assign_track_ids", "[int]"),
                 ("assign_action", "infinite_enum_coursechoicetoolactions"),
                 ("assign_course_id", "id_or_None"))
    @event_guard(check_offline=True)
    def course_choices(self, rs, event_id, course_id, track_id, position, ids,
                       include_active,
                       registration_ids, assign_track_ids, assign_action,
                       assign_course_id):
        """Manipulate course choices.

        The first four parameters (course_id, track_id, position, ids) are the
        filter parameters for the course_choices_form used for displaying
        an equally filtered form on validation errors or after successful
        submit.

        Allow assignment of multiple people in multiple tracks to one of
        their choices or a specific course.
        """
        if rs.has_validation_errors():
            return self.course_choices_form(rs, event_id)

        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()), event_id)
        courses = None
        if assign_action.enum == CourseChoiceToolActions.assign_auto:
            course_ids = self.eventproxy.list_db_courses(rs, event_id)
            courses = self.eventproxy.get_courses(rs, course_ids)

        num_committed = 0
        for registration_id in registration_ids:
            persona = personas[registrations[registration_id]['persona_id']]
            tmp = {
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
             'ids': ",".join(str(i) for i in ids), 'include_active': include_active})

    @access("event")
    @event_guard()
    @REQUESTdata(("include_active", "bool_or_None"))
    def course_stats(self, rs, event_id, include_active):
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    def batch_fees_form(self, rs, event_id, data=None, csvfields=None,
                        saldo=None):
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or {}
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['persona_id'] = csv_position.pop('id', -1)
        return self.render(rs, "batch_fees",
                           {'data': data, 'csvfields': csv_position,
                            'saldo': saldo})

    def examine_fee(self, rs, datum, expected_fees, full_payment=True):
        """Check one line specifying a paid fee.

        We test for fitness of the data itself.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: object}
        :type expected_fees: {int: decimal.Decimal}
        :type full_payment: bool
        :param full_payment: If True, only write the payment date if the fee
            was paid in full.
        :rtype: {str: object}
        :returns: The processed input datum.
        """
        event = rs.ambience['event']
        warnings = []
        infos = []
        # Allow an amount of zero to allow non-modification of amount_paid.
        amount, problems = validate.check_non_negative_decimal(
            datum['raw']['amount'].strip(), "amount")
        persona_id, p = validate.check_cdedbid(
            datum['raw']['id'].strip(), "persona_id")
        problems.extend(p)
        family_name, p = validate.check_str(
            datum['raw']['family_name'], "family_name")
        problems.extend(p)
        given_names, p = validate.check_str(
            datum['raw']['given_names'], "given_names")
        problems.extend(p)
        date, p = validate.check_date(
            datum['raw']['date'].strip(), "date")
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
                registration_id = tuple(self.eventproxy.list_registrations(
                    rs, event['id'], persona_id).keys())
                if registration_id:
                    registration_id = unwrap(registration_id)
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
                if not re.search(diacritic_patterns(re.escape(family_name)),
                                 persona['family_name'], flags=re.IGNORECASE):
                    warnings.append(('family_name',
                                     ValueError(
                                         n_("Family name doesn’t match."))))
                if not re.search(diacritic_patterns(re.escape(given_names)),
                                 persona['given_names'], flags=re.IGNORECASE):
                    warnings.append(('given_names',
                                     ValueError(
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

    def book_fees(self, rs, data, send_notifications=False):
        """Book all paid fees.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: [{str: object}]
        :rtype: bool, int
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
        except:
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
            self.logger.error(cgitb.text(sys.exc_info(), context=7))
            return False, index
        if send_notifications:
            persona_ids = tuple(e['persona_id'] for e in data)
            personas = self.coreproxy.get_personas(rs, persona_ids)
            subject = "Überweisung für {} eingetroffen".format(
                rs.ambience['event']['title'])
            for persona in personas.values():
                headers = {
                    'To': (persona['username'],),
                    'Subject': subject,
                }
                if rs.ambience['event']['orga_address']:
                    headers['Reply-To'] = rs.ambience['event']['orga_address']
                self.do_mail(rs, "transfer_received", headers,
                             {'persona': persona})
        return True, count

    @access("event", modi={"POST"})
    @REQUESTdata(("force", "bool"), ("fee_data", "str_or_None"),
                 ("checksum", "str_or_None"), ("send_notifications", "bool"),
                 ("full_payment", "bool"))
    @REQUESTfile("fee_data_file")
    @event_guard(check_offline=True)
    def batch_fees(self, rs, event_id, force, fee_data, fee_data_file,
                   checksum, send_notifications, full_payment):
        """Allow orgas to add lots paid of participant fee at once."""
        fee_data_file = check(rs, "csvfile_or_None", fee_data_file,
                              "fee_data_file")
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
            fee_data_lines, fieldnames=fields, dialect=CustomCSVDialect)
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset = {'raw': raw_entry}
            lineno += 1
            dataset['lineno'] = lineno
            data.append(self.examine_fee(
                rs, dataset, expected_fees, full_payment))
        if lineno != len(fee_data_lines):
            rs.append_validation_error(
                ("fee_data", ValueError(n_("Lines didn’t match up."))))
        open_issues = any(e['problems'] for e in data)
        saldo = sum(e['amount'] for e in data if e['amount'])
        if not force:
            open_issues = open_issues or any(e['warnings'] for e in data)
        if rs.has_validation_errors() or not data or open_issues:
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

        current_checksum = hashlib.md5(fee_data.encode()).hexdigest()
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
    def downloads(self, rs, event_id):
        """Offer documents like nametags for download."""
        return self.render(rs, "downloads")

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_nametags(self, rs, event_id, runs):
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
            shutil_copy(src, work_dir / "aka-logo.png")
            shutil_copy(src, work_dir / "orga-logo.png")
            shutil_copy(src, work_dir / "minor-pictogram.png")
            shutil_copy(src, work_dir / "multicourse-logo.png")
            for course_id in courses:
                shutil_copy(src, work_dir / "logo-{}.png".format(course_id))
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
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_puzzle(self, rs, event_id, runs):
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_puzzle(self, rs, event_id, runs):
        """Aggregate lodgement information.

        This can be printed and cut to help with distribution of
        participants. This make use of the lodge_field and the
        reserve_field.
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
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_lists(self, rs, event_id, runs):
        """Create lists to post to course rooms."""
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/downloads')
        tracks = rs.ambience['event']['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
            shutil_copy(src, work_dir / "event-logo.png")
            for course_id in courses:
                dest = work_dir / "course-logo-{}.png".format(course_id)
                path = self.conf["STORAGE_DIR"] / "course_logo" / str(course_id)
                if path.exists():
                    shutil_copy(path, dest)
                else:
                    shutil_copy(src, dest)
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
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_lists(self, rs, event_id, runs):
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
            shutil_copy(src, work_dir / "aka-logo.png")
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
    @REQUESTdata(("runs", "single_digit_int"), ("landscape", "bool"),
                 ("orgas_only", "bool"), ("part_ids", "[id]"))
    @event_guard()
    def download_participant_list(self, rs, event_id, runs, landscape,
                                  orgas_only, part_ids=None):
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
    def download_expuls(self, rs, event_id):
        """Create TeX-snippet for announcement in the exPuls."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        if not course_ids:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        courses = self.eventproxy.get_courses(rs, course_ids)
        tracks = rs.ambience['event']['tracks']
        tracks_sorted = [e['id'] for e in xsorted(tracks.values(),
                                                  key=EntitySorter.course_track)]
        tex = self.fill_template(rs, "tex", "expuls", {'courses': courses,
                                                       'tracks': tracks_sorted})
        return self.send_file(
            rs, data=tex, inline=False,
            filename="{}_expuls.tex".format(rs.ambience['event']['shortname']))

    @access("event")
    @event_guard()
    def download_csv_courses(self, rs, event_id):
        """Create CSV file with all courses"""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        if not course_ids:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")
        courses = self.eventproxy.get_courses(rs, course_ids)
        columns = ['id', 'nr', 'shortname', 'title', 'instructors', 'max_size',
                   'min_size', 'notes', 'description']
        columns.extend('fields.' + field['field_name']
                       for field in rs.ambience['event']['fields'].values()
                       if field['association'] ==
                       const.FieldAssociations.course)
        for part in xsorted(rs.ambience['event']['parts'].values(),
                           key=EntitySorter.event_part):
            columns.extend('track{}'.format(track_id)
                           for track_id in part['tracks'])

        for course in courses.values():
            for track_id in rs.ambience['event']['tracks']:
                status = 'active' if track_id in course['active_segments'] \
                    else ('cancelled' if track_id in course['segments'] else '')
                course['track{}'.format(track_id)] = status
            course.update({
                'fields.{}'.format(field['field_name']):
                    course['fields'].get(field['field_name'], '')
                for field in rs.ambience['event']['fields'].values()
                if field['association'] == const.FieldAssociations.course})
        csv_data = csv_output(xsorted(courses.values(), key=EntitySorter.course),
                              columns)
        return self.send_csv_file(
            rs, data=csv_data, inline=False, filename="{}_courses.csv".format(
                rs.ambience['event']['shortname']))

    @access("event")
    @event_guard()
    def download_csv_lodgements(self, rs, event_id):
        """Create CSV file with all courses"""
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        if not lodgement_ids:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")

        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        columns = ['id', 'moniker', 'capacity', 'reserve', 'notes']
        columns.extend('fields.' + field['field_name']
                       for field in rs.ambience['event']['fields'].values()
                       if field['association'] ==
                       const.FieldAssociations.lodgement)

        for lodgement in lodgements.values():
            lodgement.update({
                'fields.{}'.format(field['field_name']):
                    lodgement['fields'].get(field['field_name'], '')
                for field in rs.ambience['event']['fields'].values()
                if field['association'] == const.FieldAssociations.lodgement})
        csv_data = csv_output(xsorted(lodgements.values(), key=EntitySorter.lodgement),
                              columns)
        return self.send_csv_file(
            rs, data=csv_data, inline=False,
            filename="{}_lodgements.csv".format(
                rs.ambience['event']['shortname']))

    @access("event")
    @event_guard()
    def download_csv_registrations(self, rs, event_id):
        """Create CSV file with all registrations"""
        # Get data
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        all_tracks = {
            track_id: track
            for part in rs.ambience['event']['parts'].values()
            for track_id, track in part['tracks'].items()
        }

        spec = self.make_registration_query_spec(rs.ambience['event'])
        fields_of_interest = list(spec.keys())
        query = Query('qview_registration', spec, fields_of_interest, [], [])
        result = self.eventproxy.submit_general_query(
            rs, query, event_id=event_id)
        if not result:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/downloads")

        fields = []
        for csvfield in query.fields_of_interest:
            fields.extend(csvfield.split(','))

        choices, _ = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements, fixed_gettext=True)
        csv_data = csv_output(result, fields, substitutions=choices)

        return self.send_csv_file(
            rs, data=csv_data, inline=False,
            filename="{}_registrations.csv".format(
                rs.ambience['event']['shortname']))

    @access("event", modi={"GET"})
    @REQUESTdata(("agree_unlocked_download", "bool_or_None"))
    @event_guard()
    def download_export(self, rs, event_id, agree_unlocked_download):
        """Retrieve all data for this event to initialize an offline
        instance."""
        if rs.has_validation_errors():
            return self.redirect(rs, "event/show_event")

        if not (agree_unlocked_download or rs.ambience['event']['offline_lock']):
            rs.notify("info", n_("Please confirm to download a full export of "
                                 "an unlocked event."))
            return self.redirect(rs, "event/show_event")
        data = self.eventproxy.export_event(rs, event_id)
        if not data:
            rs.notify("info", n_("Empty File."))
            return self.redirect(rs, "event/show_event")
        json = json_serialize(data)
        return self.send_file(
            rs, data=json, inline=False, filename="{}_export_event.json".format(
                rs.ambience['event']['shortname']))

    @access("event")
    @event_guard()
    def download_partial_export(self, rs, event_id):
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
    def download_quick_partial_export(self, rs):
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
        events = self.eventproxy.list_db_events(rs)
        if len(events) != 1:
            ret['message'] = "Exactly one event must exist."
            return self.send_json(rs, ret)
        event_id = unwrap(events.keys())
        ret['export'] = self.eventproxy.partial_export_event(rs, event_id)
        ret['message'] = "success"
        return self.send_json(rs, ret)

    @access("event")
    @event_guard()
    def partial_import_form(self, rs, event_id):
        """First step of partial import process: Render form to upload file"""
        return self.render(rs, "partial_import")

    @access("event", modi={"POST"})
    @REQUESTfile("json_file")
    @REQUESTdata(("partial_import_data", "str_or_None"),
                 ("token", "str_or_None"))
    @event_guard(check_offline=True)
    def partial_import(self, rs, event_id, json_file, partial_import_data,
                       token):
        """Further steps of partial import process

        This takes the changes and generates a transaction token. If the new
        token agrees with the submitted token, the change were successfully
        applied, otherwise a diff-view of the changes is displayed.

        In the first iteration the data is extracted from a file upload and
        in further iterations it is embedded in the page.
        """
        if partial_import_data:
            data = check(rs, "serialized_partial_event",
                         json.loads(partial_import_data))
        else:
            data = check(rs, "serialized_partial_event_upload", json_file)
        if rs.has_validation_errors():
            return self.partial_import_form(rs, event_id)
        if event_id != data['id']:
            rs.notify("error", n_("Data from wrong event."))
            return self.partial_import_form(rs, event_id)

        # First gather infos for comparison
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(
            rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodgement_group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        lodgement_groups = self.eventproxy.get_lodgement_groups(rs, lodgement_group_ids)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        persona_ids = (
            ({e['persona_id'] for e in registrations.values()}
             | {e.get('persona_id')
                for e in data.get('registrations', {}).values() if e})
            - {None})
        personas = self.coreproxy.get_event_users(rs, persona_ids, event_id)

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

        # Fourth look for double creations
        all_current_data = self.eventproxy.partial_export_event(rs, data['id'])
        suspicious_courses = []
        for course_id, course in delta.get('courses', {}).items():
            if course_id < 0:
                for current in all_current_data['courses'].values():
                    if current == course:
                        suspicious_courses.append(course_id)
                        break
        suspicious_lodgements = []
        for lodgement_id, lodgement in delta.get('lodgements', {}).items():
            if lodgement_id < 0:
                for current in all_current_data['lodgements'].values():
                    if current == lodgement:
                        suspicious_lodgements.append(lodgement_id)
                        break

        # Fifth prepare
        rs.values['token'] = new_token
        rs.values['partial_import_data'] = json_serialize(data)
        for course in courses.values():
            course['segments'] = {
                id: id in course['active_segments']
                for id in course['segments']
            }

        # Sixth prepare summary
        def flatten_recursive_delta(data, old, prefix=""):
            ret = {}
            for key, val in data.items():
                if isinstance(val, collections.abc.Mapping):
                    tmp = flatten_recursive_delta(val, old.get(key, {}),
                                                 "{}{}.".format(prefix, key))
                    ret.update(tmp)
                else:
                    ret["{}{}".format(prefix, key)] = (old.get(key, None), val)
            return ret

        summary = {
            'changed_registrations': {
                id: flatten_recursive_delta(val, registrations[id])
                for id, val in delta.get('registrations', {}).items()
                if id > 0 and val
            },
            'new_registration_ids': tuple(xsorted(
                id for id in delta.get('registrations', {})
                if id < 0)),
            'deleted_registration_ids': tuple(xsorted(
                id for id, val in delta.get('registrations', {}).items()
                if val is None)),
            'real_deleted_registration_ids': tuple(xsorted(
                id for id, val in delta.get('registrations', {}).items()
                if val is None and registrations.get(id))),
            'changed_courses': {
                id: flatten_recursive_delta(val, courses[id])
                for id, val in delta.get('courses', {}).items()
                if id > 0 and val
            },
            'new_course_ids': tuple(xsorted(
                id for id in delta.get('courses', {}) if id < 0)),
            'deleted_course_ids': tuple(xsorted(
                id for id, val in delta.get('courses', {}).items()
                if val is None)),
            'real_deleted_course_ids': tuple(xsorted(
                id for id, val in delta.get('courses', {}).items()
                if val is None and courses.get(id))),
            'changed_lodgements': {
                id: flatten_recursive_delta(val, lodgements[id])
                for id, val in delta.get('lodgements', {}).items()
                if id > 0 and val
            },
            'new_lodgement_ids': tuple(xsorted(
                id for id in delta.get('lodgements', {}) if id < 0)),
            'deleted_lodgement_ids': tuple(xsorted(
                id for id, val in delta.get('lodgements', {}).items()
                if val is None)),
            'real_deleted_lodgement_ids': tuple(xsorted(
                id for id, val in delta.get('lodgements', {}).items()
                if val is None and lodgements.get(id))),

            'changed_lodgement_groups': {
                id: flatten_recursive_delta(val, lodgement_groups[id])
                for id, val in delta.get('lodgement_groups', {}).items()
                if id > 0 and val},
            'new_lodgement_group_ids': tuple(xsorted(
                id for id in delta.get('lodgement_groups', {}) if id < 0)),
            'real_deleted_lodgement_group_ids': tuple(xsorted(
                id for id, val in delta.get('lodgement_groups', {}).items()
                if val is None and lodgement_groups.get(id))),
        }

        changed_registration_fields = set()
        for reg in summary['changed_registrations'].values():
            changed_registration_fields |= reg.keys()
        summary['changed_registration_fields'] = tuple(xsorted(
            changed_registration_fields))
        changed_course_fields = set()
        for course in summary['changed_courses'].values():
            changed_course_fields |= course.keys()
        summary['changed_course_fields'] = tuple(xsorted(
            changed_course_fields))
        changed_lodgement_fields = set()
        for lodgement in summary['changed_lodgements'].values():
            changed_lodgement_fields |= lodgement.keys()
        summary['changed_lodgement_fields'] = tuple(xsorted(
            changed_lodgement_fields))

        reg_titles, reg_choices, course_titles, course_choices, lodgement_titles = \
            self._make_partial_import_diff_aux(
                rs, rs.ambience['event'], courses, lodgements)

        # Seventh render diff
        template_data = {
            'delta': delta,
            'registrations': registrations,
            'lodgements': lodgements,
            'lodgement_groups': lodgement_groups,
            'suspicious_lodgements': suspicious_lodgements,
            'courses': courses,
            'suspicious_courses': suspicious_courses,
            'personas': personas,
            'summary': summary,
            'reg_titles': reg_titles,
            'reg_choices': reg_choices,
            'course_titles': course_titles,
            'course_choices': course_choices,
            'lodgement_titles': lodgement_titles,
        }
        return self.render(rs, "partial_import_check", template_data)

    @staticmethod
    def _make_partial_import_diff_aux(rs, event, courses, lodgements):
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
        lodgement_entries = {l["id"]: l["moniker"]
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
            reg_titles["tracks.{}.course_id".format(track_id)] = prefix + rs.gettext("Course")
            reg_choices["tracks.{}.course_id".format(track_id)] = course_entries
            reg_titles["tracks.{}.course_instructor".format(track_id)] = prefix + rs.gettext("Instructor")
            reg_choices["tracks.{}.course_instructor".format(track_id)] = course_entries
            reg_titles["tracks.{}.choices".format(track_id)] = prefix + rs.gettext("Course Choices")
            reg_choices["tracks.{}.choices".format(track_id)] = course_entries
            course_titles["segments.{}".format(track_id)] = prefix + rs.gettext("Status")
            course_choices["segments.{}".format(track_id)] = segment_stati_entries

        for field in event['fields'].values():
            # TODO add choices?
            title = safe_filter("<i>{}</i>").format(field['field_name'])
            if field['association'] == const.FieldAssociations.registration:
                reg_titles["fields.{}".format(field['field_name'])] = title
            elif field['association'] == const.FieldAssociations.course:
                course_titles["fields.{}".format(field['field_name'])] = title
            elif field['association'] == const.FieldAssociations.lodgement:
                lodgement_titles["fields.{}".format(field['field_name'])] = title

        # Titles and choices for part-specific fields
        for part_id, part in event['parts'].items():
            if len(event['parts']) > 1:
                prefix = "{title}: ".format(title=part['shortname'])
            else:
                prefix = ""
            reg_titles["parts.{}.status".format(part_id)] = prefix + rs.gettext("Status")
            reg_choices["parts.{}.status".format(part_id)] = reg_part_stati_entries
            reg_titles["parts.{}.lodgement_id".format(part_id)] = prefix + rs.gettext("Lodgement")
            reg_choices["parts.{}.lodgement_id".format(part_id)] = lodgement_entries
            reg_titles["parts.{}.is_reserve".format(part_id)] = prefix + rs.gettext("Camping Mat")

        return reg_titles, reg_choices, course_titles, course_choices, lodgement_titles

    @access("event")
    @REQUESTdata(("preview", "bool"))
    def register_form(self, rs, event_id, preview=False):
        """Render form."""
        event = rs.ambience['event']
        tracks = event['tracks']
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'],
            event['begin'])
        minor_form_present = (
                self.conf["STORAGE_DIR"] / 'minor_form' / str(event_id)
                ).exists()
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
            if not minor_form_present and age.is_minor():
                rs.notify("info", n_("No minors may register. "
                                     "Please contact the Orgateam."))
                return self.redirect(rs, "event/show_event")
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    n_("Must be Orga to use preview."))
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    def process_registration_input(rs, event, courses, reg_questionnaire, 
                                   parts=None):
        """Helper to handle input by participants.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
        :type reg_questionnaire: [{str: object}]
        :type parts: [int] or None
        :param parts: If not None this specifies the ids of the parts this
          registration applies to (since you can apply for only some of the
          parts of an event and should not have to choose courses for the
          non-relevant parts this is important). If None the parts have to
          be provided in the input.
        :rtype: {str: object}
        :returns: registration data set
        """
        tracks = event['tracks']
        standard_params = (("mixed_lodging", "bool"), ("notes", "str_or_None"),
                           ("list_consent", "bool"))
        if parts is None:
            standard_params += (("parts", "[int]"),)
        standard = request_extractor(rs, standard_params)
        if parts is not None:
            standard['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params = (("course_choice{}_{}".format(track_id, i), "id_or_None")
                         for part_id in standard['parts']
                         for track_id in event['parts'][part_id]['tracks']
                         for i in range(event['tracks'][track_id]
                                        ['num_choices']))
        choices = request_extractor(rs, choice_params)
        instructor_params = (
            ("course_instructor{}".format(track_id), "id_or_None")
            for part_id in standard['parts']
            for track_id in event['parts'][part_id]['tracks'])
        instructor = request_extractor(rs, instructor_params)
        if not standard['parts']:
            rs.append_validation_error(
                ("parts", ValueError(n_("Must select at least one part."))))
        present_tracks = set()
        choice_getter = lambda track_id, i: choices["course_choice{}_{}".format(track_id, i)]
        for part_id in standard['parts']:
            for track_id, track in event['parts'][part_id]['tracks'].items():
                present_tracks.add(track_id)
                # Check for duplicate course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, j),
                     ValueError(n_("You cannot have the same course as %(i)s. and %(j)s. choice"), {'i': i+1, 'j': j+1}))
                    for j in range(track['num_choices'])
                    for i in range(j)
                    if (choice_getter(track_id, j) is not None
                        and choice_getter(track_id, i) == choice_getter(track_id, j)))
                # Check for unfilled mandatory course choices
                rs.extend_validation_errors(
                    ("course_choice{}_{}".format(track_id, i),
                     ValueError(n_("You must chose at least %(min_choices)s courses."),
                                {'min_choices': track['min_choices']}))
                    for i in range(track['min_choices'])
                    if choice_getter(track_id, i) is None)
        reg_parts = {part_id: {} for part_id in event['parts']}
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
        params = tuple(
            (f(entry)['field_name'],
             "{}".format(const.FieldDatatypes(f(entry)['kind']).name))
            for entry in reg_questionnaire
            if entry['field_id'] and not entry['readonly'])
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
    def register(self, rs, event_id):
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        reg_questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(const.QuestionnaireUsages.registration,)))
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, reg_questionnaire)
        if rs.has_validation_errors():
            return self.register_form(rs, event_id)
        registration['event_id'] = event_id
        registration['persona_id'] = rs.user.persona_id
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        minor_form_present = (
                self.conf["STORAGE_DIR"] / 'minor_form' / str(event_id)).exists()
        if not minor_form_present and age.is_minor():
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

        subject = "[CdE] Anmeldung für {}".format(rs.ambience['event']['title'])
        reply_to = (rs.ambience['event']['orga_address'] or
                    self.conf["EVENT_ADMIN_ADDRESS"])
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': subject,
             'Reply-To': reply_to},
            {'fee': fee, 'age': age, 'meta_info': meta_info,
             'semester_fee': semester_fee})
        self.notify_return_code(rs, new_id, success=n_("Registered for event."))
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def registration_status(self, rs, event_id):
        """Present current state of own registration."""
        reg_list = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if not reg_list:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration_id = unwrap(reg_list.keys())
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        meta_info = self.coreproxy.get_meta_info(rs)
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
        return self.render(rs, "registration_status", {
            'registration': registration, 'age': age, 'courses': courses,
            'meta_info': meta_info, 'fee': fee, 'semester_fee': semester_fee,
            'reg_questionnaire': reg_questionnaire,
        })

    @access("event")
    def amend_registration_form(self, rs, event_id):
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
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    def amend_registration(self, rs, event_id):
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id, event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        code = self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    @event_guard(check_offline=True)
    def configure_registration_form(self, rs, event_id):
        """Render form."""
        reg_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.registration)
        return self.render(rs, "configure_registration",
                           {'reg_questionnaire': reg_questionnaire,
                            'registration_fields': reg_fields})

    @access("event")
    @event_guard(check_offline=True)
    def configure_additional_questionnaire_form(self, rs, event_id):
        """Render form."""
        add_questionnaire, reg_fields = self._prepare_questionnaire_form(
            rs, event_id, const.QuestionnaireUsages.additional)
        return self.render(rs, "configure_additional_questionnaire", {
            'add_questionnaire': add_questionnaire,
            'registration_fields': reg_fields})

    def _prepare_questionnaire_form(self, rs, event_id, kind):
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
    def configure_registration(self, rs, event_id):
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
    def configure_additional_questionnaire(self, rs, event_id):
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

    def _set_questionnaire(self, rs, event_id, kind):
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
    @REQUESTdata(("preview", "bool_or_None"))
    def additional_questionnaire_form(self, rs, event_id, preview=False, 
                                      internal=False):
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
    def additional_questionnaire(self, rs, event_id):
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
        params = tuple(
            (f(entry)['field_name'],
             "{}_or_None".format(const.FieldDatatypes(f(entry)['kind']).name))
            for entry in add_questionnaire
            if entry['field_id'] and not entry['readonly'])
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
                                    other_used_fields: Collection) -> \
            Dict[const.QuestionnaireUsages, List[Mapping[str, Any]]]:
        """This handles input to configure questionnaires.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :param num: number of rows to expect
        :param reg_fields: Available fields
        :param kind: For which kind of questionnaire are these rows?
        :rtype: [{str: object}]
        """
        del_flags = request_extractor(
            rs, (("delete_{}".format(i), "bool") for i in range(num)))
        deletes = {i for i in range(num) if del_flags['delete_{}'.format(i)]}
        spec = {
            'field_id': "id_or_None",
            'title': "str_or_None",
            'info': "str_or_None",
            'input_size': "int_or_None",
            'readonly': "bool_or_None",
            'default_value': "str_or_None",
        }
        marker = 1
        while marker < 2 ** 10:
            if not unwrap(request_extractor(
                    rs, (("create_-{}".format(marker), "bool"),))):
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        indices = (set(range(num)) | {-i for i in range(1, marker)}) - deletes

        field_key = lambda anid: f"field_id_{anid}"
        readonly_key = lambda anid: f"readonly_{anid}"
        default_value_key = lambda anid: f"default_value_{anid}"

        def duplicate_constraint(idx1, idx2):
            if idx1 == idx2:
                return None
            key1 = field_key(idx1)
            key2 = field_key(idx2)
            msg = n_("Must not duplicate field.")
            return (lambda d: (not d[key1] or d[key1] != d[key2]),
                    (key1, ValueError(msg)))

        def valid_field_constraint(idx):
            key = field_key(idx)
            return (lambda d: not d[key] or d[key] in reg_fields,
                    (key, ValueError(n_("Invalid field."))))

        def fee_modifier_kind_constraint(idx):
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

        def readonly_kind_constraint(idx):
            key = readonly_key(idx)
            msg = n_("Registration questionnaire rows may not be readonly.")
            return (lambda d: (not d[key] or kind.allow_readonly()),
                    (key, ValueError(msg)))

        def duplicate_kind_constraint(idx):
            key = field_key(idx)
            msg = n_("This field is already in use in another questionnaire.")
            return (lambda d: d[key] not in other_used_fields,
                    (key, ValueError(msg)))

        constraints = tuple(filter(
            None, (duplicate_constraint(idx1, idx2)
                   for idx1 in indices for idx2 in indices)))
        constraints += tuple(itertools.chain.from_iterable(
            (valid_field_constraint(idx),
             fee_modifier_kind_constraint(idx),
             readonly_kind_constraint(idx),
             duplicate_kind_constraint(idx))
            for idx in indices))

        params = tuple(("{}_{}".format(key, i), value)
                       for i in indices for key, value in spec.items())
        data = request_extractor(rs, params, constraints)
        for idx in indices:
            dv_key = default_value_key(idx)
            field_id = data[field_key(idx)]
            if data[dv_key] is None or field_id is None:
                data[dv_key] = None
                continue
            data[dv_key] = check(rs, "by_field_datatype_or_None",
                                 data[dv_key], dv_key,
                                 kind=reg_fields[field_id]['kind'])
        questionnaire = {
            kind: list(
                {key: data["{}_{}".format(key, i)] for key in spec}
                for i in mixed_existence_sorter(indices))}
        return questionnaire

    @staticmethod
    def _sanitize_questionnaire_row(row):
        """Small helper to make validation happy.

        The invokation
        ``proxy.set_questionnaire(proxy.get_questionnaire())`` fails since
        the retrieval method provides additional information which not
        settable and thus filtered by this method.

        :type row: {str: object}
        :rtype: {str: object}
        """
        whitelist = ('field_id', 'title', 'info', 'input_size', 'readonly',
                     'default_value', 'kind')
        return {k: v for k, v in row.items() if k in whitelist}

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata(("kind", "enum_questionnaireusages"))
    def reorder_questionnaire_form(self, rs: RequestState, event_id: int,
                                   kind: const.QuestionnaireUsages) -> Response:
        """Render form."""
        if rs.has_validation_errors():
            kind = const.QuestionnaireUsages.additional
            rs.notify(
                "error", n_("Unknown questionnaire kind. Defaulted to {kind}."),
                {'kind': kind})
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
            if kind in redirects:
                return self.redirect(rs, redirects[kind])
        return self.render(rs, "reorder_questionnaire", {
            'questionnaire': questionnaire,
            'kind': kind})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    @REQUESTdata(("order", "int_csv_list"),
                 ("kind", "enum_questionnaireusages"))
    def reorder_questionnaire(self, rs: RequestState, event_id: int,
                              kind: const.QuestionnaireUsages,
                              order: Sequence[int]) -> Response:
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.has_validation_errors():
            return self.reorder_questionnaire_form(rs, event_id, kind)
        questionnaire = unwrap(self.eventproxy.get_questionnaire(
            rs, event_id, kinds=(kind,)))
        new_questionnaire = {
            kind: tuple(self._sanitize_questionnaire_row(questionnaire[i])
                        for i in order)}
        code = self.eventproxy.set_questionnaire(
            rs, event_id, new_questionnaire)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/reorder_questionnaire_form")

    @access("event")
    @event_guard()
    def show_registration(self, rs, event_id, registration_id):
        """Display all information pertaining to one registration."""
        persona = self.coreproxy.get_event_user(
            rs, rs.ambience['registration']['persona_id'], event_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        meta_info = self.coreproxy.get_meta_info(rs)
        fee = self.eventproxy.calculate_fee(rs, registration_id)
        return self.render(rs, "show_registration", {
            'persona': persona, 'age': age, 'courses': courses,
            'lodgements': lodgements, 'meta_info': meta_info, 'fee': fee,
        })

    @access("event")
    @event_guard(check_offline=True)
    @REQUESTdata(('skip', '[str]'))
    def change_registration_form(self, rs, event_id, registration_id, skip,
                                 internal=False):
        """Render form.

        The skip parameter is meant to hide certain fields and skip them when
        evaluating the submitted from in change_registration(). This can be
        used in situations, where changing those fields could override
        concurrent changes (e.g. the Check-in).


        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'event/show_registration')
        tracks = rs.ambience['event']['tracks']
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_event_user(rs, registration['persona_id'],
                                                event_id)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    def process_orga_registration_input(rs, event, do_fields=True,
                                        check_enabled=False, skip=(),
                                        do_real_persona_id=False):
        """Helper to handle input by orgas.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event. This puts less restrictions
        on the input (like not requiring different course choices).

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :param do_fields: Process custom fields of the registration(s)
        :type do_fields: bool
        :param check_enabled: Check if the "enable" checkboxes, corresponding
                              to the fields are set. This is required for the
                              multiedit page.
        :type check_enabled: bool
        :param skip: A list of field names to be entirely skipped
        :type skip: [str]
        :param do_real_persona_id: Process the `real_persona_id` field. Should
                                   only be done when CDEDB_OFFLINE_DEPLOYMENT
        :type do_real_persona_id: bool
        :rtype: {str: object}
        :returns: registration data set
        """

        def filter_parameters(params):
            """Helper function to filter parameters by `skip` list and `enabled`
            checkboxes"""
            params = [(key, kind) for key, kind in params if key not in skip]
            if not check_enabled:
                return params
            enable_params = tuple(("enable_{}".format(i), "bool")
                                  for i, t in params)
            enable = request_extractor(rs, enable_params)
            return tuple((key, kind) for key, kind in params
                         if enable["enable_{}".format(key)])

        # Extract parameters from request
        tracks = event['tracks']
        reg_params = (
            ("reg.notes", "str_or_None"), ("reg.orga_notes", "str_or_None"),
            ("reg.payment", "date_or_None"),
            ("reg.amount_paid", "non_negative_decimal"),
            ("reg.parental_agreement", "bool"), ("reg.mixed_lodging", "bool"),
            ("reg.checkin", "datetime_or_None"), ("reg.list_consent", "bool"),)
        part_params = []
        for part_id in event['parts']:
            part_params.extend((
                ("part{}.status".format(part_id), "enum_registrationpartstati"),
                ("part{}.lodgement_id".format(part_id), "id_or_None"),
                ("part{}.is_reserve".format(part_id), "bool")))
        track_params = []
        for track_id, track in tracks.items():
            track_params.extend(
                ("track{}.{}".format(track_id, key), "id_or_None")
                for key in ("course_id", "course_instructor"))
            track_params.extend(
                ("track{}.course_choice_{}".format(track_id, i), "id_or_None")
                for i in range(track['num_choices']))
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(const.FieldDatatypes(field['kind']).name))
            for field in event['fields'].values()
            if field['association'] == const.FieldAssociations.registration)

        raw_reg = request_extractor(rs, filter_parameters(reg_params))
        if do_real_persona_id:
            raw_reg.update(request_extractor(rs, filter_parameters((
                ("reg.real_persona_id", "cdedbid_or_None"),))))
        raw_parts = request_extractor(rs, filter_parameters(part_params))
        raw_tracks = request_extractor(rs, filter_parameters(track_params))
        raw_fields = request_extractor(rs, filter_parameters(field_params))

        # Build `parts`, `tracks` and `fields` dict
        new_parts = {
            part_id: {
                key: raw_parts["part{}.{}".format(part_id, key)]
                for key in ("status", "lodgement_id", "is_reserve")
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
    @REQUESTdata(('skip', '[str]'))
    def change_registration(self, rs, event_id, registration_id, skip):
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
            return self.change_registration_form(rs, event_id, registration_id,
                                                 internal=True)
        registration['id'] = registration_id
        code = self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_registration")

    @access("event")
    @event_guard(check_offline=True)
    def add_registration_form(self, rs, event_id):
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
    def add_registration(self, rs, event_id):
        """Register a participant by an orga.

        This should not be used that often, since a registration should
        singnal legal consent which is not provided this way.
        """
        persona_id = unwrap(
            request_extractor(rs, (("persona.persona_id", "cdedbid"),)))
        if (persona_id is not None
                and not self.coreproxy.verify_personas(
                    rs, (persona_id,), required_roles=("event",))):
            rs.append_validation_error(
                ("persona.persona_id", ValueError(n_("Invalid persona."))))
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
    @REQUESTdata(("ack_delete", "bool"))
    @event_guard(check_offline=True)
    def delete_registration(self, rs, event_id, registration_id, ack_delete):
        """Remove a registration."""
        if not ack_delete:
            rs.append_validation_error(
                ("ack_delete", ValueError(n_("Must be checked."))))
        if rs.has_validation_errors():
            return self.show_registration(rs, event_id, registration_id)

        blockers = self.eventproxy.delete_registration_blockers(
            rs, registration_id)
        # maybe exclude some blockers
        code = self.eventproxy.delete_registration(
            rs, registration_id, {"registration_parts", "registration_tracks",
                                  "course_choices"})
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_query")

    @access("event")
    @REQUESTdata(("reg_ids", "int_csv_list"))
    @event_guard(check_offline=True)
    def change_registrations_form(self, rs, event_id, reg_ids):
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
            rs, (r['persona_id'] for r in registrations.values()), event_id)
        for reg_id, reg in registrations.items():
            reg['gender'] = personas[reg['persona_id']]['gender']
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
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
            if len(present) == 0:
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
    @REQUESTdata(("reg_ids", "int_csv_list"))
    @event_guard(check_offline=True)
    def change_registrations(self, rs, event_id, reg_ids):
        """Make privileged changes to any information pertaining to multiple
        registrations.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], check_enabled=True)
        if rs.has_validation_errors():
            return self.change_registrations_form(rs, event_id)

        code = 1
        self.logger.info(
            "Updating registrations {} with data {}".format(reg_ids,
                                                            registration))
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
    def calculate_groups(entity_ids, event, registrations, key,
                         personas=None):
        """Determine inhabitants/attendees of lodgements/courses.

        This has to take care only to select registrations which are
        actually present (and not cancelled or such).

        :type entity_ids: [int]
        :type event: {str: object}
        :type registrations: {int: {str: object}}
        :type key: str
        :param key: one of lodgement_id or course_id, signalling what to do
        :type personas: {int: {str: object}} or None
        :param personas: If provided this is used to sort the resulting
          lists by name, so that the can be displayed sorted.
        :rtype: {(int, int): [int]}
        """
        tracks = event['tracks']
        aspect = None
        if key == "course_id":
            aspect = 'tracks'
        elif key == "lodgement_id":
            aspect = 'parts'

        def _check_belonging(entity_id, sub_id, reg_id):
            """The actual check, un-inlined."""
            instance = registrations[reg_id][aspect][sub_id]
            part = None
            if aspect == 'parts':
                part = instance
            elif aspect == 'tracks':
                part = registrations[reg_id]['parts'][tracks[sub_id]['part_id']]
            return (instance[key] == entity_id and
                    const.RegistrationPartStati(part['status']).is_present())

        if personas is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']])
        sub_ids = None
        if aspect == 'tracks':
            sub_ids = tracks.keys()
        elif aspect == 'parts':
            sub_ids = event['parts'].keys()
        return {
            (entity_id, sub_id): xsorted(
                (registration_id for registration_id in registrations
                 if _check_belonging(entity_id, sub_id, registration_id)),
                key=sorter)
            for entity_id in entity_ids
            for sub_id in sub_ids
        }

    @classmethod
    def check_lodgement_problems(cls, event, lodgements,
                                registrations, personas, inhabitants):
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        :type event: {str: object}
        :type lodgements: {int: {str: object}}
        :type registrations: {int: {str: object}}
        :type personas: {int: {str: object}}
        :type inhabitants: {(int, int): [int]}
        :rtype: [(str, int, int, [int], int)]
        :returns: problems as five-tuples of (problem description, lodgement
          id, part id, affected registrations, severeness).
        """
        ret = []

        # first some un-inlined code pieces (otherwise nesting is a bitch)
        def _mixed(group):
            """Un-inlined check whether both genders are present."""
            return any({personas[registrations[a]['persona_id']]['gender'],
                        personas[registrations[b]['persona_id']]['gender']} ==
                       {const.Genders.male, const.Genders.female}
                       for a, b in itertools.combinations(group, 2))

        def _mixing_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for mixing problems."""
            return (
                n_("Mixed lodgement with non-mixing participants."),
                lodgement_id, part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if not registrations[reg_id]['mixed_lodging']),
                3)

        def _reserve(group, part_id):
            """Un-inlined code to count the number of registrations assigned
            to a lodgement as reserve lodgers."""
            return sum(
                registrations[reg_id]['parts'][part_id]['is_reserve']
                for reg_id in group)

        def _reserve_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for reserve problems."""
            return (
                n_("Too many camping mats used."), lodgement_id,
                part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if registrations[reg_id]['parts'][part_id]['is_reserve']),
                1)

        # now the actual work
        for lodgement_id in lodgements:
            for part_id in event['parts']:
                group = inhabitants[(lodgement_id, part_id)]
                lodgement = lodgements[lodgement_id]
                num_reserve = _reserve(group, part_id)
                if len(group) > lodgement['capacity'] + lodgement['reserve']:
                    ret.append((n_("Overful lodgement."), lodgement_id, part_id,
                                tuple(), 2))
                elif len(group) - num_reserve > lodgement['capacity']:
                    ret.append((n_("Too few camping mats used."),
                                lodgement_id, part_id, tuple(), 2))
                if num_reserve > lodgement['reserve']:
                    ret.append(_reserve_problem(lodgement_id, part_id))
                if _mixed(group) and any(
                        not registrations[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                complex_gender_people = tuple(
                    reg_id
                    for reg_id in group
                    if personas[registrations[reg_id]['persona_id']]['gender']
                        in (const.Genders.other, const.Genders.not_specified))
                if complex_gender_people:
                    ret.append((n_("Non-Binary Participant."), lodgement_id,
                                part_id, complex_gender_people, 1))
        return ret

    @access("event")
    @event_guard()
    @REQUESTdata(("sort_part_id", "id_or_None"),
                 ("sortkey", "enum_lodgementssortkeys_or_None"),
                 ("reverse", "bool"))
    def lodgements(self, rs, event_id, sort_part_id=None, sortkey=None,
                   reverse=False):
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
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)

        # All inhabitants (regular and reserve) of all lodgements and all parts
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id")
        regular_inhabitant_nums = {
            k: sum(
                1 for r in v if not registrations[r]['parts'][k[1]]['is_reserve'])
            for k, v in inhabitants.items()}
        reserve_inhabitant_nums = {
            k: sum(
                1 for r in v if registrations[r]['parts'][k[1]]['is_reserve'])
            for k, v in inhabitants.items()}
        problems = self.check_lodgement_problems(
            rs.ambience['event'], lodgements, registrations, personas,
            inhabitants)
        problems_condensed = {}

        # Calculate regular_inhabitant_sum and reserve_inhabitant_sum per part
        regular_inhabitant_sum = {}
        for part_id in parts:
            lodgement_sum = 0
            for lodgement_id in lodgement_ids:
                lodgement_sum += regular_inhabitant_nums[(lodgement_id, part_id)]
            regular_inhabitant_sum[part_id] = lodgement_sum
        reserve_inhabitant_sum = {}
        for part_id in parts:
            reserve_lodgement_sum = 0
            for lodgement_id in lodgement_ids:
                reserve_lodgement_sum += reserve_inhabitant_nums[(lodgement_id, part_id)]
            reserve_inhabitant_sum[part_id] = reserve_lodgement_sum

        # Calculate sum of lodgement regular capacities and reserve
        regular_sum = 0
        reserve_sum = 0
        for lodgement in lodgements.values():
            regular_sum += lodgement['capacity']
            reserve_sum += lodgement['reserve']

        # Calculate problems_condensed (worst problem)
        for lodgement_id, part_id in itertools.product(
                lodgement_ids, parts.keys()):
            problems_here = [p for p in problems
                             if p[1] == lodgement_id and p[2] == part_id]
            problems_condensed[(lodgement_id, part_id)] = (
                max(p[4] for p in problems_here) if len(problems_here) else 0,
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
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) + [(None, None)])
        }

        # Calculate group_regular_inhabitants_sum, group_reserve_inhabitants_sum,
        # group_regular_sum and group_reserve_sum
        group_regular_inhabitants_sum = {
            (group_id, part_id):
                sum(regular_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_reserve_inhabitants_sum = {
            (group_id, part_id):
                sum(reserve_inhabitant_nums[(lodgement_id, part_id)]
                    for lodgement_id in group)
            for part_id in parts
            for group_id, group in grouped_lodgements.items()}
        group_regular_sum = {
            group_id: sum(lodgement['capacity'] for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}
        group_reserve_sum = {
            group_id: sum(lodgement['reserve'] for lodgement in group.values())
            for group_id, group in grouped_lodgements.items()}

        def sort_lodgement(lodgement, group_id):
            id, lodgement = lodgement
            lodgement_group = grouped_lodgements[group_id]
            sort = LodgementsSortkeys
            if sort.is_used_sorting(sortkey):
                if sort_part_id not in parts.keys():
                    raise werkzeug.exceptions.NotFound(n_("Invalid part id."))
                regular = regular_inhabitant_nums[(id, sort_part_id)]
                reserve = reserve_inhabitant_nums[(id, sort_part_id)]
                primary_sort = (regular if sortkey == sort.used_regular
                                else reserve)
            elif sort.is_total_sorting(sortkey):
                regular = (lodgement_group[id]['capacity']
                            if id in lodgement_group else 0)
                reserve = (lodgement_group[id]['reserve']
                           if id in lodgement_group else 0)
                primary_sort = (regular if sortkey == sort.total_regular
                                else reserve)
            elif sortkey == sort.moniker:
                primary_sort = EntitySorter.lodgement(lodgement)
            else:
                primary_sort = 0
            secondary_sort = EntitySorter.lodgement(lodgement)
            return (primary_sort, secondary_sort)

        # now sort the lodgements inside their group
        sorted_grouped_lodgements = OrderedDict([
            (group_id, OrderedDict([
                (lodgement_id, lodgement)
                for lodgement_id, lodgement
                in xsorted(lodgements.items(), reverse=reverse,
                           key=lambda e: sort_lodgement(e, group_id))
                if lodgement['group_id'] == group_id
            ]))
            for group_id, group
            in (keydictsort_filter(groups, EntitySorter.lodgement_group) + [(None, None)])
        ])

        return self.render(rs, "lodgements", {
            'groups': groups,
            'grouped_lodgements': sorted_grouped_lodgements,
            'regular_inhabitants': regular_inhabitant_nums,
            'regular_inhabitants_sum': regular_inhabitant_sum,
            'group_regular_inhabitants_sum': group_regular_inhabitants_sum,
            'reserve_inhabitants': reserve_inhabitant_nums,
            'reserve_inhabitants_sum': reserve_inhabitant_sum,
            'group_reserve_inhabitants_sum': group_reserve_inhabitants_sum,
            'group_regular_sum': group_regular_sum,
            'group_reserve_sum': group_reserve_sum,
            'regular_sum': regular_sum,
            'reserve_sum': reserve_sum,
            'problems': problems_condensed,
            'last_sortkey': sortkey,
            'last_sort_part_id': sort_part_id,
            'last_reverse': reverse,
        })

    @access("event")
    @event_guard(check_offline=True)
    def lodgement_group_summary_form(self, rs, event_id):
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
    def lodgement_group_summary(self, rs, event_id):
        """Manipulate groups of lodgements."""
        group_ids = self.eventproxy.list_lodgement_groups(rs, event_id)
        groups = process_dynamic_input(rs, group_ids.keys(), {'moniker': "str"},
                                       {'event_id': event_id})
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
    def show_lodgement(self, rs, event_id, lodgement_id):
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
            rs, tuple(e['persona_id'] for e in registrations.values()), event_id)
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)

        problems = self.check_lodgement_problems(
            rs.ambience['event'], {lodgement_id: rs.ambience['lodgement']},
            registrations, personas, inhabitants)

        if not any(l for l in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        return self.render(rs, "show_lodgement", {
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,
            'groups': groups,
        })

    @access("event")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs, event_id):
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        return self.render(rs, "create_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "group_id", "notes")
    @event_guard(check_offline=True)
    def create_lodgement(self, rs, event_id, data):
        """Add a new lodgement."""
        data['event_id'] = event_id
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(const.FieldDatatypes(field['kind']).name))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()
        }
        data = check(rs, "lodgement", data, creation=True)
        if rs.has_validation_errors():
            return self.create_lodgement_form(rs, event_id)

        new_id = self.eventproxy.create_lodgement(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event")
    @event_guard(check_offline=True)
    def change_lodgement_form(self, rs, event_id, lodgement_id):
        """Render form."""
        groups = self.eventproxy.list_lodgement_groups(rs, event_id)
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['lodgement']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['lodgement'], field_values)
        return self.render(rs, "change_lodgement", {'groups': groups})

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes", "group_id")
    @event_guard(check_offline=True)
    def change_lodgement(self, rs, event_id, lodgement_id, data):
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        data['id'] = lodgement_id
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(const.FieldDatatypes(field['kind']).name))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, "lodgement", data)
        if rs.has_validation_errors():
            return self.change_lodgement_form(rs, event_id, lodgement_id)

        code = self.eventproxy.set_lodgement(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event", modi={"POST"})
    @REQUESTdata(("ack_delete", "bool"))
    @event_guard(check_offline=True)
    def delete_lodgement(self, rs, event_id, lodgement_id, ack_delete):
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
    def manage_inhabitants_form(self, rs, event_id, lodgement_id):
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
                'reserve_{}_{}'.format(part_id, registration_id):
                    registrations[registration_id]['parts'][part_id][
                        'is_reserve']
                for registration_id in inhabitants[(lodgement_id, part_id)]
            })

        def _check_without_lodgement(registration_id, part_id):
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
        def _check_not_this_lodgement(registration_id, part_id):
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
        return self.render(rs, "manage_inhabitants", {
            'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants,
            'without_lodgement': without_lodgement,
            'selectize_data': selectize_data,
            'lodgement_names': lodgement_names})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs, event_id, lodgement_id):
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
        params = tuple(("new_{}".format(part_id), "[id_or_None]")
                       for part_id in rs.ambience['event']['parts']) \
            + tuple(itertools.chain(
                (("delete_{}_{}".format(part_id, reg_id), "bool")
                 for part_id in rs.ambience['event']['parts']
                 for reg_id in current_inhabitants[part_id]),

                (("reserve_{}_{}".format(part_id, reg_id), "bool")
                 for part_id in rs.ambience['event']['parts']
                 for reg_id in current_inhabitants[part_id])))
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        # Iterate all registrations to find changed ones
        code = 1
        for registration_id, registration in registrations.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            # Check if registration is new inhabitant or deleted inhabitant
            # in any part
            for part_id in rs.ambience['event']['parts']:
                new_inhabitant = (
                        registration_id in data["new_{}".format(part_id)])
                deleted_inhabitant = data.get(
                    "delete_{}_{}".format(part_id, registration_id), False)
                is_reserve = registration['parts'][part_id]['is_reserve']
                changed_inhabitant = (
                        registration_id in current_inhabitants[part_id]
                        and data.get("reserve_{}_{}".format(part_id,
                                                            registration_id),
                                     False) != is_reserve)
                if new_inhabitant or deleted_inhabitant:
                    new_reg['parts'][part_id] = {
                        'lodgement_id': (
                            lodgement_id if new_inhabitant else None)
                    }
                elif changed_inhabitant:
                    new_reg['parts'][part_id] = {
                        'is_reserve': data.get(
                            "reserve_{}_{}".format(part_id, registration_id),
                            False)
                    }
            if new_reg['parts']:
                code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event")
    @event_guard(check_offline=True)
    def manage_attendees_form(self, rs, event_id, course_id):
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
        def _check_without_course(registration_id, track_id):
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
        def _check_not_this_course(registration_id, track_id):
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
                    EntitySorter.persona(personas[registrations[x['id']]['persona_id']]))
            )
            for track_id in tracks
        }
        courses = self.eventproxy.list_db_courses(rs, event_id)
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
    def manage_attendees(self, rs, event_id, course_id):
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
        params = (tuple(("new_{}".format(track_id), "[id_or_None]")
                        for track_id in rs.ambience['course']['segments'])
                  + tuple(
                    ("delete_{}_{}".format(track_id, reg_id), "bool")
                    for track_id in rs.ambience['course']['segments']
                    for reg_id in current_attendees[track_id]))
        data = request_extractor(rs, params)
        if rs.has_validation_errors():
            return self.manage_attendees_form(rs, event_id, course_id)

        # Iterate all registrations to find changed ones
        code = 1
        for registration_id, registration in registrations.items():
            new_reg = {
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
    def make_registration_query_spec(event):
        """Helper to enrich ``QUERY_SPECS['qview_registration']``.

        Since each event has dynamic columns for parts and extra fields we
        have amend the query spec on the fly.

        :type event: {str: object}
        """
        tracks = event['tracks']
        spec = copy.deepcopy(QUERY_SPECS['qview_registration'])
        # note that spec is an ordered dict and we should respect the order
        for part_id, part in keydictsort_filter(event['parts'],
                                                EntitySorter.event_part):
            spec["part{0}.status".format(part_id)] = "int"
            spec["part{0}.is_reserve".format(part_id)] = "bool"
            spec["part{0}.lodgement_id".format(part_id)] = "int"
            spec["lodgement{0}.id".format(part_id)] = "id"
            spec["lodgement{0}.moniker".format(part_id)] = "str"
            spec["lodgement{0}.notes".format(part_id)] = "str"
            for f in xsorted(event['fields'].values(),
                             key=EntitySorter.event_field):
                if f['association'] == const.FieldAssociations.lodgement:
                    temp = "lodgement{0}.xfield_{1}"
                    kind = const.FieldDatatypes(f['kind']).name
                    spec[temp.format(part_id, f['field_name'])] = kind
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
        if len(event['parts']) > 1:
            spec[",".join("part{0}.status".format(part_id)
                          for part_id in event['parts'])] = "int"
            spec[",".join("part{0}.is_reserve".format(part_id)
                          for part_id in event['parts'])] = "bool"
            spec[",".join("part{0}.lodgement_id".format(part_id)
                          for part_id in event['parts'])] = "int"
            spec[",".join("lodgement{0}.id".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("lodgement{0}.moniker".format(part_id)
                          for part_id in event['parts'])] = "str"
            spec[",".join("lodgement{0}.notes".format(part_id)
                          for part_id in event['parts'])] = "str"
            for f in xsorted(event['fields'].values(), key=EntitySorter.event_field):
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
        for f in xsorted(event['fields'].values(), key=EntitySorter.event_field):
            if f['association'] == const.FieldAssociations.registration:
                kind = const.FieldDatatypes(f['kind']).name
                spec["reg_fields.xfield_{}".format(f['field_name'])] = kind
        return spec

    @staticmethod
    def make_registration_query_aux(rs, event, courses,
                                    lodgements, fixed_gettext=False):
        """Un-inlined code to prepare input for template.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
        :type lodgements: {int: {str: object}}
        :type fixed_gettext: bool
        :param fixed_gettext: whether or not to use a fixed translation
            function. True means static, False means localized.
        :rtype: ({str: dict}, {str: str})
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
        lodge_identifier = lambda l: l["moniker"]
        lodgement_choices = OrderedDict(
            (l_id, lodge_identifier(l))
            for l_id, l in keydictsort_filter(lodgements,
                                              EntitySorter.lodgement))
        # First we construct the choices
        choices = {
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
            })
            if not fixed_gettext:
                # Lodgement fields value -> description
                key = "lodgement{0}.xfield_{1}"
                choices.update({
                    key.format(part_id, field['field_name']):
                        OrderedDict(field['entries'])
                    for field in lodge_fields.values() if field['entries']
                })
        for track_id in tracks:
            choices.update({
                # Course choices for the JS selector
                "track{0}.course_id".format(track_id): course_choices,
                "track{0}.course_instructor".format(track_id): course_choices,
            })
            if not fixed_gettext:
                # Course fields value -> description
                for temp in ("course", "course_instructor"):
                    key = "{1}{0}.xfield_{2}"
                    choices.update({
                       key.format(track_id, temp, field['field_name']):
                           OrderedDict(field['entries'])
                       for field in course_fields.values() if field['entries']
                    })
        if len(event['parts']) > 1:
            choices.update({
                # RegistrationPartStati enum
                ",".join("part{0}.status".format(part_id)
                         for part_id in event['parts']): reg_part_stati_choices,
            })
        if not fixed_gettext:
            # Registration fields value -> description
            choices.update({
                "reg_fields.xfield_{}".format(field['field_name']):
                    OrderedDict(field['entries'])
                for field in reg_fields.values() if field['entries']
            })

        # Second we construct the titles
        titles = {
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
        for part_id, part in event['parts'].items():
            if len(event['parts']) > 1:
                prefix = "{shortname}: ".format(shortname=part['shortname'])
            else:
                prefix = ""
            titles.update({
                "part{0}.status".format(part_id):
                    prefix + gettext("registration status"),
                "part{0}.is_reserve".format(part_id):
                    prefix + gettext("camping mat user"),
                "part{0}.lodgement_id".format(part_id):
                    prefix + gettext("lodgement"),
                "lodgement{0}.id".format(part_id):
                    prefix + gettext("lodgement ID"),
                "lodgement{0}.moniker".format(part_id):
                    prefix + gettext("lodgement moniker"),
                "lodgement{0}.notes".format(part_id):
                    prefix + gettext("lodgement notes"),
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
                ",".join("part{0}.is_reserve".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: camping mat user"),
                ",".join("part{0}.lodgement_id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement"),
                ",".join("lodgement{0}.id".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement ID"),
                ",".join("lodgement{0}.moniker".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement moniker"),
                ",".join("lodgement{0}.notes".format(part_id)
                         for part_id in event['parts']):
                    gettext("any part: lodgement notes"),
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
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    @event_guard()
    def registration_query(self, rs, event_id, download, is_search):
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        spec = self.make_registration_query_spec(rs.ambience['event'])
        # mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None

        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        choices, titles = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = \
            self.conf["DEFAULT_QUERIES_REGISTRATION"](rs.ambience['event'], spec)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries,
            'titles': titles, 'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.has_validation_errors() and is_search:
            query.scope = "qview_registration"
            result = self.eventproxy.submit_general_query(rs, query,
                                                          event_id=event_id)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                shortname = rs.ambience['event']['shortname']
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="{}_result.csv".format(shortname))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="{}_result.json".format(shortname))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "registration_query", params)

    @staticmethod
    def make_course_view_query_spec(event):
        """Helper to enrich ``QUERY_SPECS['qview_event_course']``.

        Since each event has custom course fields we have to amend the query
        spec on the fly.

        :type event: {str: object}
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

    @staticmethod
    def make_course_view_query_aux(rs, event, courses, fixed_gettext=False):
        """Un-inlined code to prepare input for template.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
        :type fixed_gettext: bool
        :param fixed_gettext: whether or not to use a fixed translation
            function. True means static, False means localized.
        :rtype: ({str: dict}, {str: str})
        :returns: Choices for select inputs and titles for columns.
        """

        tracks = event['tracks']

        if fixed_gettext:
            gettext = rs.default_gettext
            enum_gettext = lambda x: x.name
        else:
            gettext = rs.gettext
            enum_gettext = rs.gettext

        # Construct choices.
        course_identifier = lambda c: "{}. {}".format(c["nr"], c["shortname"])
        course_choices = OrderedDict(
            xsorted((c["id"], course_identifier(c)) for c in courses.values()))
        choices = {
            "course.id": course_choices
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
        titles = {
            "course.id": gettext("course id"),
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
    @REQUESTdata(("download", "str_or_None"), ("is_search", "bool"))
    @event_guard()
    def course_query(self, rs, event_id, download, is_search):

        spec = self.make_course_view_query_spec(rs.ambience['event'])
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query",
                          spec=spec, allow_empty=False)
        else:
            query = None

        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        choices, titles = self.make_course_view_query_aux(
            rs, rs.ambience['event'], courses,
            fixed_gettext=download is not None)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}

        tracks = rs.ambience['event']['tracks']
        selection_default = ["course.shortname", ]
        for col in ("is_offered", "takes_place", "attendees"):
            selection_default += list("track{}.{}".format(t_id, col)
                                      for t_id in tracks)
        default_queries = []

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries,
            'titles': titles, 'selection_default': selection_default,
        }

        if not rs.has_validation_errors() and is_search:
            query.scope = "qview_event_course"
            result = self.eventproxy.submit_general_query(
                rs, query, event_id=event_id)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    fields.extend(csvfield.split(','))
                shortname = rs.ambience['event']['shortname']
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_csv_file(
                        rs, data=csv_data, inline=False,
                        filename="{}_course_result.csv".format(shortname))
                elif download == "json":
                    json_data = query_result_to_json(
                        result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename="{}_course_result.json".format(shortname))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "course_query", params)

    @access("event")
    @event_guard(check_offline=True)
    def checkin_form(self, rs, event_id):
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
    @REQUESTdata(("registration_id", "id"))
    @event_guard(check_offline=True)
    def checkin(self, rs, event_id, registration_id):
        """Check a participant in."""
        if rs.has_validation_errors():
            return self.checkin_form(rs, event_id)
        registration = self.eventproxy.get_registration(rs, registration_id)
        if registration['event_id'] != event_id:
            return werkzeug.exceptions.NotFound(n_("Wrong associated event."))
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

    @access("event")
    @REQUESTdata(("field_id", "id_or_None"),
                 ("reg_ids", "int_csv_list_or_None"))
    @event_guard(check_offline=True)
    def field_set_select(self, rs, event_id, field_id, reg_ids):
        """Select a field for manipulation across all registrations."""
        if rs.has_validation_errors():
            return self.render(rs, "field_set_select")
        if field_id is None:
            registrations = self.eventproxy.get_registrations(rs, reg_ids)
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
            reg_order = xsorted(
                registrations.keys(),
                key=lambda anid: EntitySorter.persona(
                    personas[registrations[anid]['persona_id']]))
            registrations = OrderedDict(
                (reg_id, registrations[reg_id]) for reg_id in reg_order)
            return self.render(rs, "field_set_select",
                               {'reg_ids': reg_ids,
                                'registrations': registrations,
                                'personas': personas})
        else:
            if field_id not in rs.ambience['event']['fields']:
                return werkzeug.exceptions.NotFound(
                    n_("Wrong associated event."))
            field = rs.ambience['event']['fields'][field_id]
            if field['association'] != const.FieldAssociations.registration:
                return werkzeug.exceptions.NotFound(
                    n_("Wrong associated field."))
            return self.redirect(rs, "event/field_set_form",
                                 {'field_id': field_id,
                                  'reg_ids': (','.join(str(i) for i in reg_ids)
                                              if reg_ids else None)})

    @access("event")
    @REQUESTdata(("field_id", "id"),
                 ("reg_ids", "int_csv_list_or_None"))
    @event_guard(check_offline=True)
    def field_set_form(self, rs, event_id, field_id, reg_ids, internal=False):
        """Render form.

        The internal flag is used if the call comes from another frontend
        function to disable further redirection on validation errors.
        """
        if rs.has_validation_errors() and not internal:
            return self.redirect(rs, "event/registration_query")
        if field_id not in rs.ambience['event']['fields']:
            return werkzeug.exceptions.NotFound(n_("Wrong associated event."))
        field = rs.ambience['event']['fields'][field_id]
        if field['association'] != const.FieldAssociations.registration:
            return werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        if reg_ids:
            registration_ids = reg_ids
        else:
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        ordered = xsorted(
            registrations.keys(),
            key=lambda anid: EntitySorter.persona(
                personas[registrations[anid]['persona_id']]))
        values = {
            "input{}".format(registration_id):
                registration['fields'].get(field['field_name'])
            for registration_id, registration in registrations.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "field_set", {
            'registrations': registrations, 'personas': personas,
            'ordered': ordered,
            'reg_ids': reg_ids})

    @access("event", modi={"POST"})
    @REQUESTdata(("field_id", "id"),
                 ("reg_ids", "int_csv_list_or_None"))
    @event_guard(check_offline=True)
    def field_set(self, rs, event_id, field_id, reg_ids):
        """Modify a specific field on all registrations."""
        if field_id not in rs.ambience['event']['fields']:
            return werkzeug.exceptions.NotFound(n_("Wrong associated event."))
        field = rs.ambience['event']['fields'][field_id]
        if field['association'] != const.FieldAssociations.registration:
            return werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        kind = "{}_or_None".format(const.FieldDatatypes(field['kind']).name)
        data_params = tuple(("input{}".format(registration_id), kind)
                            for registration_id in registration_ids)
        data = request_extractor(rs, data_params)
        if rs.has_validation_errors():
            return self.field_set_form(rs, event_id, internal=True)

        # If no list of registration_ids is given as parameter get all
        # registrations
        if reg_ids:
            registration_ids = reg_ids
        else:
            registration_ids = self.eventproxy.list_registrations(rs, event_id)

        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        code = 1
        for registration_id, registration in registrations.items():
            if (data["input{}".format(registration_id)]
                    != registration['fields'].get(field['field_name'])):
                new = {
                    'id': registration_id,
                    'fields': {
                        field['field_name']:
                            data["input{}".format(registration_id)]
                    }
                }
                code *= self.eventproxy.set_registration(rs, new)
        self.notify_return_code(rs, code)

        # redirect to query filtered by registration_ids
        query = Query(
            "qview_registration",
            self.make_registration_query_spec(rs.ambience['event']),
            ("persona.given_names", "persona.family_name", "persona.username",
             "reg.id", "reg_fields.xfield_{}".format(field["field_name"])),
            (("reg.id", QueryOperators.oneof, registration_ids),),
            (("persona.family_name", True), ("persona.given_names", True),)
        )
        return self.redirect(rs, "event/registration_query",
                             querytoparams_filter(query))

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs, event_id):
        """Lock an event for offline usage."""
        code = self.eventproxy.lock_event(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @REQUESTfile("json")
    @event_guard()
    def unlock_event(self, rs, event_id, json):
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        data = check(rs, "serialized_event_upload", json)
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)
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
    @REQUESTdata(("ack_archive", "bool"),
                 ("create_past_event", "bool"))
    @event_guard(check_offline=True)
    def archive_event(self, rs, event_id, ack_archive, create_past_event):
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
    @REQUESTdata(("ack_delete", "bool"))
    @event_guard(check_offline=True)
    def delete_event(self, rs, event_id, ack_delete):
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
    @REQUESTdata(("phrase", "str"), ("kind", "str"), ("aux", "id_or_None"))
    def select_registration(self, rs, phrase, kind, aux):
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
        * orga_registration: Id of the event you are orga of
        """
        if rs.has_validation_errors():
            return self.send_json(rs, {})

        spec_additions = {}
        search_additions = []
        event = None
        num_preview_personas = (self.conf["NUM_PREVIEW_PERSONAS_CORE_ADMIN"]
                                if {"core_admin", "meta_admin"} & rs.user.roles
                                else self.conf["NUM_PREVIEW_PERSONAS"])
        if kind == "orga_registration":
            event = self.eventproxy.get_event(rs, aux)
            if "event_admin" not in rs.user.roles:
                if rs.user.persona_id not in event['orgas']:
                    raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
            if aux is None:
                return self.send_json(rs, {})
        else:
            return self.send_json(rs, {})

        data = None

        anid, errs = validate.check_id(phrase, "phrase")
        if not errs:
            tmp = self.eventproxy.get_registrations(rs, (anid,))
            if tmp:
                tmp = unwrap(tmp)
                if tmp['event_id'] == aux:
                    data = [tmp]

        # Don't query, if search phrase is too short
        if not data and len(phrase) < self.conf["NUM_PREVIEW_CHARS"]:
            return self.send_json(rs, {})

        terms = []
        if data is None:
            terms = tuple(t.strip() for t in phrase.split(' ') if t)
            valid = True
            for t in terms:
                _, errs = validate.check_non_regex(t, "phrase")
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
                data = self.eventproxy.submit_general_query(
                    rs, query, event_id=aux)

        # Strip data to contain at maximum `num_preview_personas` results
        if len(data) > num_preview_personas:
            tmp = xsorted(data, key=lambda e: e['id'])
            data = tmp[:num_preview_personas]

        def name(x):
            return "{} {}".format(x['given_names'], x['family_name'])

        # Check if name occurs multiple times to add email address in this case
        counter = collections.defaultdict(lambda: 0)
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
    @REQUESTdata(("phrase", "str"))
    def quick_show_registration(self, rs, event_id, phrase):
        """Allow orgas to quickly retrieve a registration.

        The search phrase may be anything: a numeric id or a string
        matching the data set.
        """
        if rs.has_validation_errors():
            return self.show_event(rs, event_id)

        anid, errs = validate.check_cdedbid(phrase, "phrase")
        if not errs:
            tmp = self.eventproxy.list_registrations(rs, event_id,
                                                     persona_id=anid)
            if tmp:
                tmp = unwrap(tmp.keys())
                return self.redirect(rs, "event/show_registration",
                                     {'registration_id': tmp})

        anid, errs = validate.check_id(phrase, "phrase")
        if not errs:
            tmp = self.eventproxy.get_registrations(rs, (anid,))
            if tmp:
                tmp = unwrap(tmp)
                if tmp['event_id'] == event_id:
                    return self.redirect(rs, "event/show_registration",
                                         {'registration_id': tmp['id']})

        terms = tuple(t.strip() for t in phrase.split(' ') if t)
        valid = True
        for t in terms:
            _, errs = validate.check_non_regex(t, "phrase")
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
        elif len(result) > 0:
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
            elif len(result) > 0:
                params = querytoparams_filter(query)
                return self.redirect(rs, "event/registration_query",
                                     params)
        rs.notify("warning", n_("No registration found."))
        return self.show_event(rs, event_id)

    @access("event_admin")
    @REQUESTdata(("codes", "[int]"), ("event_id", "id_or_None"),
                 ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_log(self, rs, codes, event_id, offset, length, persona_id,
                 submitted_by, additional_info, time_start, time_stop):
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
            submitted_by=submitted_by, additional_info=additional_info,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        event_ids = {entry['event_id'] for entry in log if entry['event_id']}
        registration_map = self.eventproxy.get_registration_map(rs, event_ids)
        events = self.eventproxy.get_events(rs, event_ids)
        all_events = self.eventproxy.list_db_events(rs)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "view_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'events': events,'all_events': all_events,
            'registration_map': registration_map, 'loglinks': loglinks})

    @access("event")
    @event_guard()
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("submitted_by", "cdedbid_or_None"),
                 ("additional_info", "str_or_None"),
                 ("offset", "int_or_None"),
                 ("length", "positive_int_or_None"),
                 ("time_start", "datetime_or_None"),
                 ("time_stop", "datetime_or_None"))
    def view_event_log(self, rs, codes, event_id, offset, length, persona_id,
                       submitted_by, additional_info, time_start, time_stop):
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
            submitted_by=submitted_by, additional_info=additional_info,
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
