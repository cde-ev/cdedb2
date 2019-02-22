#!/usr/bin/env python3

"""Services for the event realm."""

import cgitb
from collections import OrderedDict
import copy
import csv
import decimal
import itertools
import os
import pathlib
import re
import sys
import tempfile
import operator

import psycopg2.extensions
import werkzeug

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, csv_output,
    check_validation as check, event_guard, query_result_to_json,
    REQUESTfile, request_extractor, cdedbid_filter, querytoparams_filter,
    xdictsort_filter, enum_entries_filter)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input, Query
from cdedb.common import (
    n_, name_key, merge_dicts, determine_age_class, deduct_years, AgeClasses,
    unwrap, now, ProxyShim, json_serialize, glue, CourseChoiceToolActions,
    CourseFilterPositions, diacritic_patterns, open_utf8, shutil_copy)
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import cdedb.validation as validate


class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_event_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs, connpool, auxilliary=False):
        super().finalize_session(rs, connpool, auxilliary=auxilliary)
        if "event" in rs.user.roles:
            rs.user.orga = self.eventproxy.orga_info(rs, rs.user.persona_id)

    def render(self, rs, templatename, params=None):
        params = params or {}
        if 'event' in rs.ambience:
            params['is_locked'] = self.is_locked(rs.ambience['event'])
            if rs.user.persona_id:
                params['is_registered'] = bool(
                    self.eventproxy.list_registrations(
                        rs, rs.ambience['event']['id'], rs.user.persona_id))
        return super().render(rs, templatename, params=params)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def is_locked(self, event):
        """Shorthand to deremine locking state of an event.

        :type event: {str: object}
        :rtype: bool
        """
        return event['offline_lock'] != self.conf.CDEDB_OFFLINE_DEPLOYMENT

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

    @access("persona")
    def index(self, rs):
        """Render start page."""
        open_event_list = self.eventproxy.list_visible_events(rs)
        open_events = self.eventproxy.get_events(rs, open_event_list.keys())
        orga_events = self.eventproxy.get_events(rs, rs.user.orga)
        visible_event_list = self.eventproxy.list_db_events(rs,
                                                            visible_only=True)
        other_events = self.eventproxy.get_events(
            rs, set(visible_event_list) - set(open_event_list))
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
                enum_entries_filter(const.Genders, rs.gettext))
        }
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        default_queries = self.conf.DEFAULT_QUERIES['qview_event_user']
        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'default_queries': default_queries, 'query': query}
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_event_user"
            result = self.eventproxy.submit_general_query(rs, query)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    for field in csvfield.split(','):
                        fields.append(field.split('.')[-1])
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=csv_data, inline=False,
                        filename=rs.gettext("result.csv"))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename=rs.gettext("result.json"))
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

    @access("event")
    def show_event(self, rs, event_id):
        """Display event organized via DB."""
        params = {}
        params['orgas'] = self.coreproxy.get_personas(
            rs, rs.ambience['event']['orgas'])
        if event_id in rs.user.orga or self.is_admin(rs):
            params['institutions'] = self.pasteventproxy.list_institutions(rs)
            params['minor_form_present'] = (self.conf.STORAGE_DIR / 'minor_form'
                                            / str(event_id)).exists()
        elif not rs.ambience['event']['is_visible']:
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        return self.render(rs, "show_event", params)

    @access("event")
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
    @event_guard(check_offline=True)
    def change_event_form(self, rs, event_id):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        merge_dicts(rs.values, rs.ambience['event'])
        return self.render(rs, "change_event",
                           {'institutions': institutions,
                            'accounts': self.conf.EVENT_BANK_ACCOUNTS})

    @access("event", modi={"POST"})
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "mail_text", "use_questionnaire",
        "notes", "lodge_field", "reserve_field", "is_visible",
        "is_course_list_visible")
    @event_guard(check_offline=True)
    def change_event(self, rs, event_id, data):
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, "event", data)
        if rs.errors:
            return self.change_event_form(rs, event_id)
        code = self.eventproxy.set_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    def get_minor_form(self, rs, event_id):
        """Retrieve minor form."""
        if not rs.ambience['event']['is_visible']:
            raise werkzeug.exceptions.Forbidden(
                n_("The event is not published yet."))
        path = self.conf.STORAGE_DIR / "minor_form" / str(event_id)
        return self.send_file(
            rs, mimetype="application/pdf",
            filename=rs.gettext("minor_form.pdf"), path=path)

    @access("event", modi={"POST"})
    @REQUESTfile("minor_form")
    @event_guard(check_offline=True)
    def change_minor_form(self, rs, event_id, minor_form):
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check(rs, 'pdffile', minor_form, "minor_form")
        if rs.errors:
            return self.show_event(rs, event_id)
        path = self.conf.STORAGE_DIR / 'minor_form' / str(event_id)
        with open(str(path), 'wb') as f:
            f.write(minor_form)
        rs.notify("success", n_("Minor form updated."))
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @REQUESTdata(("orga_id", "cdedbid"))
    @event_guard(check_offline=True)
    def add_orga(self, rs, event_id, orga_id):
        """Make an additional persona become orga."""
        if not rs.errors and not self.eventproxy.check_orga_addition_limit(
                rs, event_id):
            rs.errors.append(("orga_id",
                              ValueError(n_("Rate-limit reached."))))
        if rs.errors:
            return self.show_event(rs, event_id)
        new = {
            'id': event_id,
            'orgas': rs.ambience['event']['orgas'] | {orga_id}
        }
        code = self.eventproxy.set_event(rs, new)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @REQUESTdata(("orga_id", "id"))
    @event_guard(check_offline=True)
    def remove_orga(self, rs, event_id, orga_id):
        """Demote a persona.

        This can drop your own orga role (but only if you're admin).
        """
        if rs.errors:
            return self.show_event(rs, event_id)
        if orga_id == rs.user.persona_id and not self.is_admin(rs):
            rs.notify("error", n_("Not allowed to remove yourself as orga."))
            return self.show_event(rs, event_id)
        new = {
            'id': event_id,
            'orgas': rs.ambience['event']['orgas'] - {orga_id}
        }
        code = self.eventproxy.set_event(rs, new)
        self.notify_return_code(rs, code)
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
                for k in ('title', 'shortname', 'num_choices', 'sortkey'):
                    current["track_{}_{}_{}".format(k, part_id, track_id)] = \
                        track[k]
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
        return self.render(rs, "part_summary", {
            'referenced_parts': referenced_parts,
            'referenced_tracks': referenced_tracks,
            'has_registrations': has_registrations})

    @staticmethod
    def process_part_input(rs, parts, has_registrations):
        """This handles input to configure the parts.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type parts: {int: {str: object}}
        :param parts: parts to process
        :type has_registrations: bool
        :rtype: {int: {str: object}}
        """
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
                             ('num_choices', 'int'), ('sortkey', 'int')))

        def track_excavator(req_data, part_id, track_id):
            """
            Helper function to create a single track's data dict from the
            extracted request data.
            """
            return {
                k: req_data['track_{}_{}_{}'.format(k, part_id, track_id)]
                for k in ('title', 'shortname', 'num_choices', 'sortkey')}

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
        data = request_extractor(rs, params)
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
                    newtrack = track_excavator(request_extractor(rs, params),
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
                    newtrack = track_excavator(request_extractor(rs, params),
                                               -new_part_id, -marker)
                    ret[-new_part_id]['tracks'][-marker] = newtrack
                else:
                    break
                marker += 1
            rs.values['track_create_last_index'][-new_part_id] = marker - 1

        # Handle deleted parts
        for part_id in deletes:
            ret[part_id] = None
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def part_summary(self, rs, event_id):
        """Manipulate the parts of an event."""
        has_registrations = self.eventproxy.has_registrations(rs, event_id)
        parts = self.process_part_input(
            rs, rs.ambience['event']['parts'], has_registrations)
        if rs.errors:
            return self.part_summary_form(rs, event_id)
        for part_id, part in rs.ambience['event']['parts'].items():
            if parts.get(part_id) == part:
                # remove unchanged
                del parts[part_id]
        event = {
            'id': event_id,
            'parts': parts
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
        is_referenced = set()
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        for row in questionnaire:
            if row['field_id']:
                is_referenced.add(row['field_id'])
        if rs.ambience['event']['lodge_field']:
            is_referenced.add(rs.ambience['event']['lodge_field'])
        if rs.ambience['event']['reserve_field']:
            is_referenced.add(rs.ambience['event']['reserve_field'])
        return self.render(rs, "field_summary", {
            'is_referenced': is_referenced})

    @staticmethod
    def process_field_input(rs, fields):
        """This handles input to configure the fields.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type fields: [int]
        :param fields: ids of fields
        :rtype: {int: {str: object}}
        """
        delete_flags = request_extractor(
            rs, (("delete_{}".format(field_id), "bool") for field_id in fields))
        deletes = {field_id for field_id in fields
                   if delete_flags['delete_{}'.format(field_id)]}
        ret = {}
        params = lambda anid: (("kind_{}".format(anid), "str"),
                               ("association_{}".format(anid),
                                "enum_fieldassociations"),
                               ("entries_{}".format(anid), "str_or_None"))
        for field_id in fields:
            if field_id not in deletes:
                tmp = request_extractor(rs, params(field_id))
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
                               ("kind_-{}".format(anid), "str"),
                               ("association_-{}".format(anid),
                                "enum_fieldassociations"),
                               ("entries_-{}".format(anid), "str_or_None"))
        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                tmp = request_extractor(rs, params(marker))
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
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def field_summary(self, rs, event_id):
        """Manipulate the fields of an event."""
        fields = self.process_field_input(
            rs, rs.ambience['event']['fields'].keys())
        if rs.errors:
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
        return self.redirect(rs, "event/field_summary_form")

    @access("event_admin")
    def create_event_form(self, rs):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        return self.render(rs, "create_event",
                           {'institutions': institutions,
                            'accounts': self.conf.EVENT_BANK_ACCOUNTS})

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("event_begin", "date"), ("event_end", "date"),
                 ("orga_ids", "str"))
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "mail_text", "use_questionnaire",
        "notes")
    def create_event(self, rs, event_begin, event_end, orga_ids, data):
        """Create a new event organized via DB."""
        if orga_ids:
            data['orgas'] = {check(rs, "cdedbid", anid.strip(), "orga_ids")
                             for anid in orga_ids.split(",")}
        # multi part events will have to edit this later on
        data['parts'] = {
            -1: {
                'tracks': {},
                'title': data['title'],
                'shortname': data['shortname'],
                'part_begin': event_begin,
                'part_end': event_end,
                'fee': decimal.Decimal(0),
            }
        }
        data = check(rs, "event", data, creation=True)
        if rs.errors:
            return self.create_event_form(rs)
        new_id = self.eventproxy.create_event(rs, data)
        # TODO create mailing lists
        self.notify_return_code(rs, new_id, success=n_("Event created."))
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event")
    @event_guard()
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        params = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            registrations = {
                k: v
                for k, v in
                self.eventproxy.get_registrations(rs, registration_ids).items()
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
            params['is_removable'] = self.eventproxy.is_course_removable(
                rs, course_id)
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
             "{}_or_None".format(field['kind']))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.course)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, "course", data)
        if rs.errors:
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
            rs.notify("error", n_("Event without tracks forbids courses"))
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
        data = check(rs, "course", data, creation=True)
        if rs.errors:
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
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_course(rs, event_id, course_id)
        if not self.eventproxy.is_course_removable(rs, course_id):
            rs.notify("error", n_("Course in use cannot be deleted."))
            return self.redirect(rs, 'event/show_course')
        code = self.eventproxy.delete_course(rs, course_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/course_stats")

    @access("event")
    @event_guard()
    def stats(self, rs, event_id):
        """Present an overview of the basic stats."""
        tracks = rs.ambience['event']['tracks']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        stati = const.RegistrationPartStati
        get_age = lambda u: determine_age_class(
            u['birthday'], rs.ambience['event']['begin'])
        tests1 = OrderedDict((
            ('pending', (lambda e, r, p: (
                    p['status'] == stati.applied))),
            (' payed', (lambda e, r, p: (
                    p['status'] == stati.applied
                    and r['payment']))),
            ('participant', (lambda e, r, p: (
                    p['status'] == stati.participant))),
            (' u18', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']])
                         == AgeClasses.u18)))),
            (' u16', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']])
                         == AgeClasses.u16)))),
            (' u14', (lambda e, r, p: (
                    (p['status'] == stati.participant)
                    and (get_age(personas[r['persona_id']])
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
                    and get_age(personas[r['persona_id']]).is_minor()
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

        tests2 = OrderedDict((
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
            for i in range(max(t['num_choices'] for t in tracks.values())):
                tests2['in {}. choice'.format(i + 1)] = (lambda e, r, p, t: (
                        p['status'] == stati.participant
                        and t['course_id']
                        and len(t['choices']) > i
                        and (t['choices'][i] == t['course_id'])))
            for key, test in tests2.items():
                per_track_statistics[key] = {
                    track_id: sum(
                        1 for r in registrations.values()
                        if test(rs.ambience['event'], r,
                                r['parts'][tracks[track_id]['part_id']],
                                r['tracks'][track_id]))
                    for track_id in tracks}
        tests3 = {
            # Add tests (id: lambda(event, reg, part, track)) to add filtered
            # lists of participants by event part
        }
        sorter = lambda registration_id: name_key(
            personas[registrations[registration_id]['persona_id']])
        per_part_listings = {
            key: {
                part_id: sorted(
                    (registration_id
                     for registration_id, r in registrations.items()
                     if test(rs.ambience['event'], r, r['parts'][part_id])),
                    key=sorter)
                for part_id in rs.ambience['event']['parts']
            }
            for key, test in tests3.items()
        }
        tests4 = {
            'wrong choice': (lambda e, r, p, t: (
                    p['status'] == stati.participant
                    and t['course_id']
                    and t['course_id'] != t['course_instructor']
                    and (t['course_id'] not in
                         t['choices']
                         [:e['tracks'][t['track_id']]['num_choices']]))),
        }
        sorter = lambda registration_id: name_key(
            personas[registrations[registration_id]['persona_id']])
        per_track_listings = {
            key: {
                track_id: sorted(
                    (registration_id
                     for registration_id, reg in registrations.items()
                     if test(rs.ambience['event'], reg, reg['parts'][part_id],
                             reg['tracks'][track_id])),
                    key=sorter)
                for part_id, part in rs.ambience['event']['parts'].items()
                for track_id in part['tracks']
            }
            for key, test in tests4.items()
        }

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
        involved_filter = (
            'part{part}.status{part}',
            QueryOperators.oneof,
            [x.value for x in stati if x.is_involved()],
        )
        participant_filter = (
            'part{part}.status{part}',
            QueryOperators.equal,
            stati.participant.value,
        )
        # Query filters for all the statistics defined and calculated above.
        # They are customized and inserted into the query on the fly by
        # get_query()
        query_filters = {
            'pending': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.applied.value),),
            ' payed': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.applied.value),
                ("reg.payment", QueryOperators.nonempty, None),),
            'participant': (participant_filter,),
            ' u18': (
                participant_filter,
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(rs.ambience['event']['begin'], 18)),),
            ' u16': (
                participant_filter,
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(rs.ambience['event']['begin'], 16)),),
            ' u14': (
                participant_filter,
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(rs.ambience['event']['begin'], 14)),),
            ' checked in': (
                participant_filter,
                ("reg.checkin", QueryOperators.nonempty, None),),
            ' not checked in': (
                participant_filter,
                ("reg.checkin", QueryOperators.empty, None),),
            ' orgas': (
                ('persona.id', QueryOperators.oneof,
                 rs.ambience['event']['orgas']),),
            'waitlist': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.waitlist.value),),
            'guest': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.guest.value),),
            'total involved': (involved_filter,),
            ' not payed': (
                involved_filter,
                ("reg.payment", QueryOperators.empty, None),),
            ' no parental agreement': (
                involved_filter,
                ("persona.birthday", QueryOperators.greater,
                 deduct_years(rs.ambience['event']['begin'], 18)),
                ("reg.parental_agreement", QueryOperators.equal, False),),
            'no lodgement': (
                ('part{part}.status{part}', QueryOperators.oneof,
                 [x.value for x in stati if x.is_present()]),
                ('part{part}.lodgement_id{part}', QueryOperators.empty, None)),
            'cancelled': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.cancelled.value),),
            'rejected': (
                ('part{part}.status{part}', QueryOperators.equal,
                 stati.rejected.value),),
            'total': (
                ('part{part}.status{part}', QueryOperators.unequal,
                 stati.not_applied.value),),

            'all instructors': (
                participant_filter,
                ('track{track}.course_instructor{track}',
                 QueryOperators.nonempty, None),),
            'instructors': (
                participant_filter,
                ('track{track}.is_course_instructor{track}',
                 QueryOperators.equal, True),),
            'no course': (
                participant_filter,
                ('track{track}.course_id{track}', QueryOperators.empty, None),
                ('persona.id', QueryOperators.otherthan,
                 rs.ambience['event']['orgas']),)
        }
        query_additional_fields = {
            ' payed': ('reg.payment',),
            ' u18': ('persona.birthday',),
            ' u16': ('persona.birthday',),
            ' u14': ('persona.birthday',),
            ' checked in': ('reg.checkin',),
            'total involved': ('part{part}.status{part}',),
            'instructors': ('track{track}.course_instructor{track}',),
            'all instructors': ('track{track}.course_instructor{track}',
                                'track{track}.course_id{track}',),
        }

        def get_query(category, part_id, track_id=None):
            if category not in query_filters:
                return None
            q = copy.deepcopy(base_query)
            for f in query_filters[category]:
                q.constraints.append(
                    (f[0].format(track=track_id, part=part_id), f[1], f[2]))
            if category in query_additional_fields:
                for f in query_additional_fields[category]:
                    q.fields_of_interest.append(f.format(track=track_id,
                                                         part=part_id))
            return q

        return self.render(rs, "stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'per_part_statistics': per_part_statistics,
            'per_track_statistics': per_track_statistics,
            'per_part_listings': per_part_listings,
            'per_track_listings': per_track_listings,
            'get_query': get_query})

    @access("event")
    @REQUESTdata(("course_id", "id_or_None"), ("track_id", "id_or_None"),
                 ("position", "infinite_enum_coursefilterpositions_or_None"),
                 ("ids", "int_csv_list_or_None"))
    @event_guard()
    def course_choices_form(self, rs, event_id, course_id, track_id, position,
                            ids):
        """Provide an overview of course choices.

        This allows flexible filtering of the displayed registrations.
        """
        tracks = rs.ambience['event']['tracks']
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)

        if rs.errors:
            registration_ids = all_reg_ids
            registrations = all_regs
            personas = self.coreproxy.get_personas(rs, (r['persona_id'] for r in
                                                        registrations.values()))
        else:
            registration_ids = self.eventproxy.registrations_by_course(
                rs, event_id, course_id, track_id, position, ids)
            registrations = self.eventproxy.get_registrations(
                rs, registration_ids.keys())
            personas = self.coreproxy.get_personas(
                rs, registration_ids.values())

        course_infos = {}
        stati = const.RegistrationPartStati
        reg_part = lambda registration, track_id: \
            registration['parts'][tracks[track_id]['part_id']]
        for course_id, course in courses.items():
            for track_id in tracks:
                assigned = sum(
                    1 for reg in all_regs.values()
                    if reg_part(reg, track_id)['status'] == stati.participant
                    and reg['tracks'][track_id]['course_id'] == course_id)
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
                "track{0}.course_id{0}".format(track_id)
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
                sorted(registrations.items(),
                       key=lambda reg: name_key(
                           personas[reg[1]['persona_id']]))),
            'course_infos': course_infos,
            'corresponding_query': corresponding_query,
            'filter_entries': filter_entries,
            'action_entries': action_entries})

    @access("event", modi={"POST"})
    @REQUESTdata(("registration_ids", "[int]"), ("track_ids", "[int]"),
                 ("action", "infinite_enum_coursechoicetoolactions"),
                 ("course_id", "id_or_None"))
    @event_guard(check_offline=True)
    def course_choices(self, rs, event_id, registration_ids, track_ids, action,
                       course_id):
        """Manipulate course choices.

        Allow assignment of multiple people in multiple tracks to one of
        their choices or a specific course.
        """
        if rs.errors:
            return self.course_choices_form(rs, event_id)

        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        courses = None
        if action.enum == CourseChoiceToolActions.assign_auto:
            course_ids = self.eventproxy.list_db_courses(rs, event_id)
            courses = self.eventproxy.get_courses(rs, course_ids)

        code = 1
        for registration_id in registration_ids:
            tmp = {
                'id': registration_id,
                'tracks': {}
            }
            for track_id in track_ids:
                reg_part = registrations[registration_id]['parts'][
                    tracks[track_id]['part_id']]
                reg_track = registrations[registration_id]['tracks'][track_id]
                if (reg_part['status']
                        != const.RegistrationPartStati.participant):
                    continue
                if action.enum == CourseChoiceToolActions.specific_rank:
                    choice = reg_track['choices'][action.int]
                    tmp['tracks'][track_id] = {'course_id': choice}
                elif action.enum == CourseChoiceToolActions.assign_fixed:
                    tmp['tracks'][track_id] = {'course_id': course_id}
                elif action.enum == CourseChoiceToolActions.assign_auto:
                    cid = reg_track['course_id']
                    if cid and track_id in courses[cid]['active_segments']:
                        # Do not modify a valid assignment
                        continue
                    instructor = reg_track['course_instructor']
                    if (instructor
                            and track_id in courses[instructor]
                            ['active_segments']):
                        # Let instructors instruct
                        tmp['tracks'][track_id] = {'course_id': instructor}
                        continue
                    for choice in (
                            reg_track['choices'][
                            :tracks[track_id]['num_choices']]):
                        if track_id in courses[choice]['active_segments']:
                            # Assign first possible choice
                            tmp['tracks'][track_id] = {'course_id': choice}
                            break
                    else:
                        rs.notify("error", n_("No choice available."))
            if tmp['tracks']:
                code *= self.eventproxy.set_registration(rs, tmp)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/course_choices_form")

    @access("event")
    @event_guard()
    def course_stats(self, rs, event_id):
        """List courses.

        Provide an overview of the number of choices and assignments for
        all courses.
        """
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
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for track_id, track in tracks.items()
                for i in range(track['num_choices'])
            }
            for course_id in course_ids
        }
        assign_counts = {
            course_id: {
                track_id: sum(
                    1 for reg in registrations.values()
                    if (reg['tracks'][track_id]['course_id'] == course_id
                        and (reg['parts'][track['part_id']]['status']
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for track_id, track in tracks.items()
            }
            for course_id in course_ids
        }
        return self.render(rs, "course_stats", {
            'courses': courses, 'choice_counts': choice_counts,
            'assign_counts': assign_counts})

    @access("event")
    @event_guard(check_offline=True)
    def batch_fees_form(self, rs, event_id, data=None, csvfields=None):
        """Render form.

        The ``data`` parameter contains all extra information assembled
        during processing of a POST request.
        """
        data = data or {}
        csvfields = csvfields or tuple()
        csv_position = {key: ind for ind, key in enumerate(csvfields)}
        csv_position['persona_id'] = csv_position.pop('id', -1)
        return self.render(rs, "batch_fees",
                           {'data': data, 'csvfields': csv_position})

    def examine_fee(self, rs, datum):
        """Check one line specifying a paid fee.

        We test for fitness of the data itself.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type datum: {str: object}
        :rtype: {str: object}
        :returns: The processed input datum.
        """
        event = rs.ambience['event']
        warnings = []
        date, problems = validate.check_date(datum['raw']['date'], "date")
        amount, p = validate.check_non_negative_decimal(
            datum['raw']['amount'], "amount")
        problems.extend(p)
        persona_id, p = validate.check_cdedbid(
            datum['raw']['id'], "persona_id")
        problems.extend(p)
        family_name, p = validate.check_str(
            datum['raw']['family_name'], "family_name")
        problems.extend(p)
        given_names, p = validate.check_str(
            datum['raw']['given_names'], "given_names")
        problems.extend(p)

        registration_id = None
        if persona_id:
            try:
                persona = self.coreproxy.get_persona(rs, persona_id)
            except KeyError:
                problems.append(('persona_id',
                                 ValueError(
                                     n_("No Member with ID {p_id} found."),
                                     {"p_id": persona_id})))
            else:
                registration_id = tuple(self.eventproxy.list_registrations(
                    rs, event['id'], persona_id).keys())
                if registration_id:
                    registration_id = unwrap(registration_id)
                    registration = self.eventproxy.get_registration(
                        rs, registration_id)
                    if registration['payment']:
                        warnings.append(('persona_id',
                                         ValueError(n_("Already paid."))))
                    relevant_stati = (const.RegistrationPartStati.applied,
                                      const.RegistrationPartStati.waitlist,
                                      const.RegistrationPartStati.participant,)
                    fee = sum(event['parts'][part_id]['fee']
                              for part_id, part in registration['parts'].items()
                              if part['status'] in relevant_stati)
                    if amount and amount < fee:
                        problems.append(('amount',
                                         ValueError(n_("Not enough money."))))
                    if amount and amount > fee:
                        warnings.append(('amount',
                                         ValueError(n_("Too much money."))))
                else:
                    problems.append(('persona_id',
                                     ValueError(n_("No registration found."))))
                if not re.search(diacritic_patterns(family_name),
                                 persona['family_name'], flags=re.IGNORECASE):
                    warnings.append(('family_name',
                                     ValueError(
                                         n_("Family name doesn't match."))))
                if not re.search(diacritic_patterns(given_names),
                                 persona['given_names'], flags=re.IGNORECASE):
                    warnings.append(('given_names',
                                     ValueError(
                                         n_("Given names don't match."))))
        datum.update({
            'persona_id': persona_id,
            'registration_id': registration_id,
            'date': date,
            'amount': amount,
            'warnings': warnings,
            'problems': problems,
        })
        return datum

    def book_fees(self, rs, data):
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
                for index, datum in enumerate(data):
                    update = {
                        'id': datum['registration_id'],
                        'payment': datum['date'],
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
        return True, count

    @access("event", modi={"POST"})
    @REQUESTdata(("force", "bool"), ("fee_data", "str"))
    @event_guard(check_offline=True)
    def batch_fees(self, rs, event_id, force, fee_data):
        """Allow orgas to add lots paid of participant fee at once."""
        fee_data = fee_data or ''
        fee_data_lines = fee_data.splitlines()
        fields = ('date', 'amount', 'id', 'family_name', 'given_names')
        reader = csv.DictReader(
            fee_data_lines, fieldnames=fields, delimiter=';',
            quoting=csv.QUOTE_MINIMAL, quotechar='"', doublequote=False,
            escapechar='\\')
        data = []
        lineno = 0
        for raw_entry in reader:
            dataset = {'raw': raw_entry}
            lineno += 1
            dataset['lineno'] = lineno
            data.append(self.examine_fee(rs, dataset))
        if lineno != len(fee_data_lines):
            rs.errors.append(("fee_data",
                              ValueError(n_("Lines didn't match up."))))
        open_issues = any(e['problems'] for e in data)
        if not force:
            open_issues = open_issues or any(e['warnings'] for e in data)
        if rs.errors or not data or open_issues:
            return self.batch_fees_form(rs, event_id, data=data,
                                        csvfields=fields)

        # Here validation is finished
        success, num = self.book_fees(rs, data)
        if success:
            rs.notify("success", n_("Committed {num} fees."), {'num': num})
            return self.redirect(rs, "event/show_event")
        else:
            if num is None:
                rs.notify("warning", n_("DB serialization error."))
            else:
                rs.notify("error", n_("Unexpected error on line {num}."),
                          {'num': num})
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
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        tex = self.fill_template(rs, "tex", "nametags", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'courses': courses})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            with open_utf8(work_dir / "nametags.tex", 'w') as f:
                f.write(tex)
            src = self.conf.REPOSITORY_PATH / "misc/logo.png"
            shutil_copy(src, work_dir / "aka-logo.png")
            shutil_copy(src, work_dir / "orga-logo.png")
            shutil_copy(src, work_dir / "minor-pictogram.png")
            shutil_copy(src, work_dir / "multicourse-logo.png")
            for course_id in courses:
                shutil_copy(src, work_dir / "logo-{}.png".format(course_id))
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                n_("nametags.tex"), runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_puzzle(self, rs, event_id, runs):
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        event = rs.ambience['event']
        tracks = event['tracks']
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
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for track_id, track in tracks.items() for i in
                range(track['num_choices'])
            }
            for course_id in course_ids
        }
        tex = self.fill_template(rs, "tex", "course_puzzle", {
            'courses': courses, 'counts': counts,
            'registrations': registrations, 'personas': personas})
        return self.serve_latex_document(rs, tex, "course_puzzle", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_puzzle(self, rs, event_id, runs):
        """Aggregate lodgement information.

        This can be printed and cut to help with distribution of
        participants. This make use of the lodge_field and the
        reserve_field.
        """
        event = rs.ambience['event']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                event['begin'])
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        tex = self.fill_template(rs, "tex", "lodgement_puzzle", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas})
        return self.serve_latex_document(rs, tex, "lodgement_puzzle", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_lists(self, rs, event_id, runs):
        """Create lists to post to course rooms."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        for p_id, p in personas.items():
            p['age'] = determine_age_class(
                p['birthday'], rs.ambience['event']['begin'])
        attendees = self.calculate_groups(
            courses, rs.ambience['event'], registrations, key="course_id",
            personas=personas)
        instructors = {}
        for c_id, course in courses.items():
            for t_id in course['active_segments']:
                instructors[(c_id, t_id)] = [
                    r_id
                    for r_id in attendees[(c_id, t_id)]
                    if (registrations[r_id]['tracks'][t_id]['course_instructor']
                        == c_id)
                ]
            if 'course_id' in course['fields']:
                del course['fields']['course_id']
        tex = self.fill_template(rs, "tex", "course_lists", {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'instructors': instructors,
        })
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = pathlib.Path(tmp_dir, rs.ambience['event']['shortname'])
            work_dir.mkdir()
            with open_utf8(work_dir / "course_lists.tex", 'w') as f:
                f.write(tex)
            for course_id in courses:
                shutil_copy(
                    self.conf.REPOSITORY_PATH / "misc/logo.png",
                    work_dir / "logo-{}.png".format(course_id))
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                n_("course_lists.tex"), runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_lists(self, rs, event_id, runs):
        """Create lists to post to lodgements."""
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
            with open_utf8(work_dir / "lodgement_lists.tex", 'w') as f:
                f.write(tex)
            shutil_copy(
                self.conf.REPOSITORY_PATH / "misc/logo.png",
                work_dir / "aka-logo.png")
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                n_("lodgement_lists.tex"), runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"), ("landscape", "bool"),
                 ("orgas_only", "bool"))
    @event_guard()
    def download_participant_list(self, rs, event_id, runs, landscape,
                                  orgas_only):
        """Create list to send to all participants."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in (self.eventproxy.get_registrations(rs, registration_ids)
                         .items())
            if any(part['status'] == const.RegistrationPartStati.participant
                   for part in v['parts'].values())}
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        ordered = sorted(
            registrations.keys(),
            key=lambda anid: name_key(
                personas[registrations[anid]['persona_id']]))
        tex = self.fill_template(rs, "tex", "participant_list", {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'ordered': ordered,
            'orientation': "landscape" if landscape else "portrait",
            'orgas_only': orgas_only,
        })
        return self.serve_latex_document(rs, tex, "participant_list", runs)

    @access("event")
    @event_guard()
    def download_expuls(self, rs, event_id):
        """Create TeX-snippet for announcement in the exPuls."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        tex = self.fill_template(rs, "tex", "expuls", {'courses': courses})
        return self.send_file(rs, data=tex, inline=False,
                              filename=rs.gettext("expuls.tex"))

    @access("event")
    @event_guard()
    def download_csv_courses(self, rs, event_id):
        """Create CSV file with all courses"""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        columns = ['id', 'nr', 'shortname', 'title', 'instructors', 'max_size',
                   'min_size', 'notes', 'description']
        columns.extend('fields.' + field['field_name']
                       for field in rs.ambience['event']['fields'].values()
                       if field['association'] ==
                       const.FieldAssociations.course)
        for part in sorted(rs.ambience['event']['parts'].values(),
                           key=lambda x: x['part_begin']):
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
        csv_data = csv_output(sorted(courses.values(), key=lambda c: c['id']),
                              columns)
        return self.send_file(
            rs, data=csv_data, inline=False, filename=rs.gettext("courses.csv"))

    @access("event")
    @event_guard()
    def download_csv_lodgements(self, rs, event_id):
        """Create CSV file with all courses"""
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
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
        csv_data = csv_output(sorted(lodgements.values(),
                                     key=lambda c: c['id']),
                              columns)
        return self.send_file(
            rs, data=csv_data, inline=False,
            filename=rs.gettext("lodgements.csv"))

    @access("event")
    @event_guard()
    def download_csv_registrations(self, rs, event_id):
        """Create CSV file with all registrations"""
        # Get data
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        all_tracks = {
            track_id: track
            for part in rs.ambience['event']['parts'].values()
            for track_id, track in part['tracks'].items()
        }

        # Construct CSV columns
        columns = ['id', 'persona.id', 'persona.birthday', 'persona.telephone',
                   'persona.mobile', 'persona.address',
                   'persona.address_supplement', 'persona.postal_code',
                   'persona.location', 'persona.country', 'payment',
                   'parental_agreement', 'mixed_lodging', 'foto_consent',
                   'notes', 'orga_notes', 'checkin',
                   # 'creation_time', 'modification_time',
                   ]
        columns.extend('fields.' + field['field_name']
                       for field in rs.ambience['event']['fields'].values()
                       if field['association'] ==
                       const.FieldAssociations.registration)
        # Construct columns for parts and lodgement data
        for part_id in sorted(rs.ambience['event']['parts'].keys()):
            columns.extend("part{}.{}".format(part_id, f)
                           for f in ('status', 'lodgement.id', 'is_reserve',
                                     'lodgement.moniker'))
            columns.extend(
                "part{}.lodgement.fields.{}".format(part_id,
                                                    field['field_name'])
                for field in rs.ambience['event']['fields'].values()
                if field['association'] == const.FieldAssociations.lodgement)
        # Construct columns for courses' data for each track
        for part in sorted(rs.ambience['event']['parts'].values(),
                           key=lambda x: x['part_begin']):
            for track_id in sorted(part['tracks']):
                columns.extend(
                    'track{}.{}'.format(track_id, f)
                    for f in ('course.id', 'course.nr', 'course.shortname',
                              'course.title'))
                columns.extend([
                    "track{}.course.fields.{}".format(track_id,
                                                      field['field_name'])
                    for field in rs.ambience['event']['fields'].values()
                    if field['association'] == const.FieldAssociations.course])
                columns.extend('track{}.choice{}.{}'.format(track_id, i, f)
                               for i in range(part['tracks'][track_id]
                                              ['num_choices'])
                               for f in ('id', 'nr'))
                columns.extend(
                    'track{}.course_instructor.{}'.format(track_id, f)
                    for f in ('id', 'nr'))

        # Flatten registrations and insert course/lodement data:
        for registration in registrations.values():
            # Persona data and data fields
            registration.update({
                'persona.{}'.format(k): v
                for k, v in personas[registration['persona_id']].items()})
            registration.update(
                {
                    'fields.{}'.format(field['field_name']):
                        registration['fields'].get(field['field_name'], '')
                    for field in rs.ambience['event']['fields'].values()
                    if (field['association'] ==
                        const.FieldAssociations.registration)}
            )
            # Parts and lodgement data
            for part_id, part in registration['parts'].items():
                registration.update({'part{}.{}'.format(part_id, k): v
                                     for k, v in part.items()})
                registration.update({
                    'part{}.lodgement.{}'.format(part_id, f):
                        lodgements[part['lodgement_id']][f]
                        if part['lodgement_id'] else ''
                    for f in ('id', 'moniker')})
                registration.update({
                    'part{}.lodgement.fields.{}'.format(
                        part_id, field['field_name']): (
                        lodgements[part['lodgement_id']]['fields'].get(
                            field['field_name'], '') if part['lodgement_id']
                        else '')
                    for field in rs.ambience['event']['fields'].values()
                    if (field['association'] ==
                        const.FieldAssociations.lodgement)
                })
            # Courses' data for each track
            for track_id, track in registration['tracks'].items():
                registration.update({
                    'track{}.course.{}'.format(track_id, f):
                        courses[track['course_id']][f]
                        if track['course_id'] else ''
                    for f in ('id', 'nr', 'shortname', 'title')
                })
                registration.update({
                    'track{}.course.fields.{}'.format(
                        track_id, field['field_name']): (
                        courses[track['course_id']]['fields'].get(
                            field['field_name'], '') if track['course_id']
                        else '')
                    for field in rs.ambience['event']['fields'].values()
                    if (field['association'] ==
                        const.FieldAssociations.course)
                })
                for i, choice in enumerate(track['choices']):
                    registration.update({
                        'track{}.choice{}.{}'.format(track_id, i, f):
                            courses[choice][f] if choice else ''
                        for f in ('id', 'nr')})
                for i in range(len(track['choices']),
                               all_tracks[track_id]['num_choices']):
                    registration.update({
                        'track{}.choice{}.{}'.format(track_id, i, f): ''
                        for f in ('id', 'nr')})
                registration.update({
                    'track{}.course_instructor.{}'.format(track_id, f):
                        courses[track['course_instructor']][f]
                        if track['course_instructor'] else ''
                    for f in ('id', 'nr')})

        csv_data = csv_output(sorted(registrations.values(),
                                     key=lambda c: c['id']),
                              columns)
        return self.send_file(
            rs, data=csv_data, inline=False,
            filename=rs.gettext("registrations.csv"))

    @access("event")
    @event_guard()
    def download_export(self, rs, event_id):
        """Retrieve all data for this event to initialize an offline
        instance."""
        data = self.eventproxy.export_event(rs, event_id)
        json = json_serialize(data)
        return self.send_file(rs, data=json, inline=False,
                              filename=rs.gettext("export_event.json"))

    @access("event")
    def register_form(self, rs, event_id):
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if rs.user.persona_id in registrations.values():
            rs.notify("info", n_("Already registered."))
            return self.redirect(rs, "event/registration_status")
        if not rs.ambience['event']['is_open']:
            rs.notify("warning", n_("Registration not open."))
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", n_("Event locked."))
            return self.redirect(rs, "event/show_event")
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'],
            rs.ambience['event']['begin'])
        minor_form_present = (
                self.conf.STORAGE_DIR / 'minor_form' / str(event_id)).exists()
        if not minor_form_present and age.is_minor():
            rs.notify("info", n_("No minors may register."))
            return self.redirect(rs, "event/show_event")
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in xdictsort_filter(courses, 'nr', pad=True)
                       if track_id in course['active_segments']]
            for track_id in tracks}
        # by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', rs.ambience['event']['parts'])
        return self.render(rs, "register", {
            'persona': persona, 'age': age, 'courses': courses,
            'course_choices': course_choices})

    @staticmethod
    def process_registration_input(rs, event, courses, parts=None):
        """Helper to handle input by participants.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
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
        standard_params = (("mixed_lodging", "bool"), ("foto_consent", "bool"),
                           ("notes", "str_or_None"))
        if parts is None:
            standard_params += (("parts", "[int]"),)
        standard = request_extractor(rs, standard_params)
        if parts is not None:
            standard['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params = (("course_choice{}_{}".format(track_id, i), "id")
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
            rs.errors.append(("parts",
                              ValueError(n_("Must select at least one part."))))
        present_tracks = set()
        for part_id in standard['parts']:
            for track_id, track in event['parts'][part_id]['tracks'].items():
                present_tracks.add(track_id)
                cids = {choices["course_choice{}_{}".format(track_id, i)]
                        for i in range(track['num_choices'])}
                if len(cids) != track['num_choices']:
                    rs.errors.extend(
                        ("course_choice{}_{}".format(track_id, i),
                         ValueError(n_("Must choose different courses.")))
                        for i in range(track['num_choices']))
        if not standard['foto_consent']:
            rs.errors.append(("foto_consent",
                              ValueError(
                                  n_("Must consent for participation."))))
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
                    instructor.get("course_instructor{}".format(track_id)),
            }
            for track_id in tracks
        }
        for track_id in present_tracks:
            reg_tracks[track_id]['choices'] = tuple(
                choices["course_choice{}_{}".format(track_id, i)]
                for i in range(tracks[track_id]['num_choices']))
        registration = {
            'mixed_lodging': standard['mixed_lodging'],
            'foto_consent': standard['foto_consent'],
            'notes': standard['notes'],
            'parts': reg_parts,
            'tracks': reg_tracks,
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        registration = self.process_registration_input(rs, rs.ambience['event'],
                                                       courses)
        if rs.errors:
            return self.register_form(rs, event_id)
        registration['event_id'] = event_id
        registration['persona_id'] = rs.user.persona_id
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        minor_form_present = (
                self.conf.STORAGE_DIR / 'minor_form' / str(event_id)).exists()
        if not minor_form_present and age.is_minor():
            rs.notify("error", n_("No minors may register."))
            return self.redirect(rs, "event/show_event")
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration)
        meta_info = self.coreproxy.get_meta_info(rs)
        fee = sum(rs.ambience['event']['parts'][part_id]['fee']
                  for part_id, entry in registration['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved())
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': n_('Registered for CdE event')},
            {'fee': fee, 'age': age, 'meta_info': meta_info})
        self.notify_return_code(rs, new_id, success=n_("Registered for event."))
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def registration_status(self, rs, event_id):
        """Present current state of own registration."""
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        fee = sum(rs.ambience['event']['parts'][part_id]['fee']
                  for part_id, entry in registration['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved())
        return self.render(rs, "registration_status", {
            'registration': registration, 'age': age, 'courses': courses,
            'fee': fee})

    @access("event")
    def amend_registration_form(self, rs, event_id):
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        if (rs.ambience['event']['registration_soft_limit'] and
                now() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("warning",
                      n_("Registration closed, no changes possible."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in xdictsort_filter(courses, 'nr', pad=True)
                       if track_id in course['active_segments']]
            for track_id in tracks}
        non_trivials = {}
        for track_id, track in registration['tracks'].items():
            for i, choice in enumerate(track['choices']):
                param = "course_choice{}_{}".format(track_id, i)
                non_trivials[param] = choice
        for track_id, entry in registration['tracks'].items():
            param = "course_instructor{}".format(track_id)
            non_trivials[param] = entry['course_instructor']
        stat = lambda track: registration['parts'][track['part_id']]['status']
        involved_tracks = {
            track_id for track_id, track in tracks.items()
            if const.RegistrationPartStati(stat(track)).is_involved()}
        merge_dicts(rs.values, non_trivials, registration)
        return self.render(rs, "amend_registration", {
            'age': age, 'courses': courses, 'course_choices': course_choices,
            'involved_tracks': involved_tracks,
        })

    @access("event", modi={"POST"})
    def amend_registration(self, rs, event_id):
        """Change information provided during registering.

        Participants are not able to change for which parts they applied on
        purpose. For this they have to communicate with the orgas.
        """
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if (rs.ambience['event']['registration_soft_limit'] and
                now() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("error", n_("No changes allowed anymore."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        stored = self.eventproxy.get_registration(rs, registration_id)
        registration = self.process_registration_input(
            rs, rs.ambience['event'], courses, parts=stored['parts'])
        if rs.errors:
            return self.amend_registration_form(rs, event_id)

        registration['id'] = registration_id
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        code = self.eventproxy.set_registration(rs, registration)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    @REQUESTdata(("preview", "bool_or_None"))
    def questionnaire_form(self, rs, event_id, preview=False):
        """Render form."""
        if not preview:
            registration_id = self.eventproxy.list_registrations(
                rs, event_id, persona_id=rs.user.persona_id)
            if not registration_id:
                rs.notify("warning", n_("Not registered for event."))
                return self.redirect(rs, "event/show_event")
            registration_id = unwrap(registration_id, keys=True)
            registration = self.eventproxy.get_registration(rs, registration_id)
            if not rs.ambience['event']['use_questionnaire']:
                rs.notify("warning", n_("Questionnaire disabled."))
                return self.redirect(rs, "event/registration_status")
            if self.is_locked(rs.ambience['event']):
                rs.notify("info", n_("Event locked."))
            merge_dicts(rs.values, registration['fields'])
        else:
            if event_id not in rs.user.orga and not self.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    n_("Must be Orga to use Preview."))
            if not rs.ambience['event']['use_questionnaire']:
                rs.notify("info", n_("Questionnaire is not enabled yet."))
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        return self.render(rs, "questionnaire", {
            'questionnaire': questionnaire,
            'preview': preview})

    @access("event", modi={"POST"})
    def questionnaire(self, rs, event_id):
        """Fill in additional fields.

        The registration form was very sparse and asked only for minimal
        information, to allow for maximum flexibility with this, which in
        contrast allows the orgas to query their applicants for all kind of
        additional information. What exactly is queried is configured on a
        per event basis.
        """
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", n_("Not registered for event."))
            return self.redirect(rs, "event/show_event")
        if not rs.ambience['event']['use_questionnaire']:
            rs.notify("error", n_("Questionnaire disabled."))
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", n_("Event locked."))
            return self.redirect(rs, "event/registration_status")
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        f = lambda entry: rs.ambience['event']['fields'][entry['field_id']]
        params = tuple(
            (f(entry)['field_name'], "{}_or_None".format(f(entry)['kind']))
            for entry in questionnaire
            if entry['field_id'] and not entry['readonly'])
        data = request_extractor(rs, params)
        if rs.errors:
            return self.questionnaire_form(rs, event_id)

        code = self.eventproxy.set_registration(rs, {
            'id': registration_id, 'fields': data,
        })
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/questionnaire_form")

    @access("event")
    @event_guard()
    def questionnaire_summary_form(self, rs, event_id):
        """Render form."""
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        current = {
            "{}_{}".format(key, i): value
            for i, entry in enumerate(questionnaire)
            for key, value in entry.items()}
        merge_dicts(rs.values, current)
        registration_fields = {
            k: v for k, v in rs.ambience['event']['fields'].items()
            if v['association'] == const.FieldAssociations.registration}
        return self.render(rs, "questionnaire_summary", {
            'questionnaire': questionnaire,
            'registration_fields': registration_fields})

    @staticmethod
    def process_questionnaire_input(rs, num, reg_fields):
        """This handles input to configure the questionnaire.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type num: int
        :param num: number of rows to expect
        :type reg_fields: [int]
        :param reg_fields: Available field ids
        :rtype: [{str: object}]
        """
        delete_flags = request_extractor(
            rs, (("delete_{}".format(i), "bool") for i in range(num)))
        deletes = {i for i in range(num) if delete_flags['delete_{}'.format(i)]}
        spec = {
            'field_id': "id_or_None",
            'title': "str_or_None",
            'info': "str_or_None",
            'input_size': "int_or_None",
            'readonly': "bool_or_None",
        }
        params = tuple(("{}_{}".format(key, i), value)
                       for i in range(num) if i not in deletes
                       for key, value in spec.items())
        data = request_extractor(rs, params)
        questionnaire = tuple(
            {key: data["{}_{}".format(key, i)] for key in spec}
            for i in range(num) if i not in deletes
        )
        marker = 1
        while marker < 2 ** 10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_extractor(rs, params)
                questionnaire += ({key: data["{}_-{}".format(key, marker)]
                                   for key in spec},)
            else:
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        for i, row in enumerate(questionnaire):
            if row['field_id'] and row['field_id'] not in reg_fields:
                rs.errors.append(("field_id_{}".format(i),
                                  ValueError(n_("Invalid field."))))
        return questionnaire

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def questionnaire_summary(self, rs, event_id):
        """Manipulate the questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        registration_fields = {
            k for k, v in rs.ambience['event']['fields'].items()
            if v['association'] == const.FieldAssociations.registration}
        new_questionnaire = self.process_questionnaire_input(
            rs, len(questionnaire), registration_fields)
        if rs.errors:
            return self.questionnaire_summary_form(rs, event_id)
        code = self.eventproxy.set_questionnaire(rs, event_id,
                                                 new_questionnaire)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/questionnaire_summary_form")

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
        whitelist = ('field_id', 'title', 'info', 'input_size', 'readonly',)
        return {k: v for k, v in row.items() if k in whitelist}

    @access("event")
    @event_guard(check_offline=True)
    def reorder_questionnaire_form(self, rs, event_id):
        """Render form."""
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        return self.render(rs, "reorder_questionnaire", {
            'questionnaire': questionnaire})

    @access("event", modi={"POST"})
    @REQUESTdata(("order", "int_csv_list"))
    @event_guard(check_offline=True)
    def reorder_questionnaire(self, rs, event_id, order):
        """Shuffle rows of the orga designed form.

        This is strictly speaking redundant functionality, but it's pretty
        laborious to do without.
        """
        if rs.errors:
            return self.reorder_questionnaire_form(rs, event_id)
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        new_questionnaire = tuple(
            self._sanitize_questionnaire_row(questionnaire[i])
            for i in order)
        code = self.eventproxy.set_questionnaire(rs, event_id,
                                                 new_questionnaire)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/questionnaire_summary_form")

    @access("event")
    @event_guard()
    def show_registration(self, rs, event_id, registration_id):
        """Display all information pertaining to one registration."""
        persona = self.coreproxy.get_event_user(
            rs, rs.ambience['registration']['persona_id'])
        age = determine_age_class(
            persona['birthday'], rs.ambience['event']['begin'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        return self.render(rs, "show_registration", {
            'persona': persona, 'age': age, 'courses': courses,
            'lodgements': lodgements,
        })

    @access("event")
    @event_guard(check_offline=True)
    def change_registration_form(self, rs, event_id, registration_id):
        """Render form."""
        tracks = rs.ambience['event']['tracks']
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_event_user(rs, registration['persona_id'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in xdictsort_filter(courses, 'nr', pad=True)
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
            'course_choices': course_choices, 'lodgements': lodgements})

    @staticmethod
    def process_orga_registration_input(rs, event, do_fields=True,
                                        check_enabled=False,
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
        :param do_real_persona_id: Process the `real_persona_id` field. Should
                                   only be done when CDEDB_OFFLINE_DEPLOYMENT
        :type do_real_persona_id: bool
        :rtype: {str: object}
        :returns: registration data set
        """

        # Helper function to filter parameters by `enabled` checkbox
        def filter_parameters(params):
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
            ("reg.payment", "date_or_None"), ("reg.parental_agreement", "bool"),
            ("reg.mixed_lodging", "bool"), ("reg.checkin", "datetime_or_None"),
            ("reg.foto_consent", "bool"))
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
             "{}_or_None".format(field['kind']))
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
                rs.errors.extend(
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
    def change_registration(self, rs, event_id, registration_id):
        """Make privileged changes to any information pertaining to a
        registration.

        Strictly speaking this makes a lot of the other functionality
        redundant (like managing the lodgement inhabitants), but it would be
        much more cumbersome to always use this interface.
        """
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'],
            do_real_persona_id=self.conf.CDEDB_OFFLINE_DEPLOYMENT)
        if rs.errors:
            return self.change_registration_form(rs, event_id, registration_id)

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
                       in xdictsort_filter(courses, 'nr', pad=True)
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
            rs.errors.append(("persona.persona_id",
                              ValueError(n_("Invalid persona."))))
        if not rs.errors and self.eventproxy.list_registrations(
                rs, event_id, persona_id=persona_id):
            rs.errors.append(("persona.persona_id",
                              ValueError(n_("Already registered."))))
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], do_fields=False,
            do_real_persona_id=self.conf.CDEDB_OFFLINE_DEPLOYMENT)
        if not rs.errors and not self.eventproxy.check_orga_addition_limit(
                rs, event_id):
            rs.errors.append(("persona.persona_id",
                              ValueError(n_("Rate-limit reached."))))
        if rs.errors:
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
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_registration(rs, event_id, registration_id)

        code = self.eventproxy.delete_registration(rs, registration_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_query")

    @access("event")
    @REQUESTdata(("reg_ids", "int_csv_list"))
    @event_guard(check_offline=True)
    def change_registrations_form(self, rs, event_id, reg_ids):
        """Render form for changing multiple registrations."""
        if rs.errors:
            return self.registration_query(rs, event_id, download=None,
                                           is_search=False)
        # Get information about registrations, courses and lodgements
        tracks = rs.ambience['event']['tracks']
        registrations = self.eventproxy.get_registrations(rs, reg_ids)
        if not registrations:
            rs.notify("error", n_("No participants found to edit."))
            return self.redirect(rs, 'event/registration_query')

        personas = self.coreproxy.get_event_users(
            rs, (r['persona_id'] for r in registrations.values()))
        for reg_id, reg in registrations.items():
            reg['gender'] = personas[reg['persona_id']]['gender']
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            track_id: [course_id
                       for course_id, course
                       in xdictsort_filter(courses, 'nr', pad=True)
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
                        reg_values['track{}.{}'.format(part_id, key)] = value
                        reg_values[
                            'enable_track{}.{}'.format(part_id, key)] = True

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
        if rs.errors:
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
            sorter = lambda anid: name_key(
                personas[registrations[anid]['persona_id']])
        sub_ids = None
        if aspect == 'tracks':
            sub_ids = tracks.keys()
        elif aspect == 'parts':
            sub_ids = event['parts'].keys()
        return {
            (entity_id, sub_id): sorted(
                (registration_id for registration_id in registrations
                 if _check_belonging(entity_id, sub_id, registration_id)),
                key=sorter)
            for entity_id in entity_ids
            for sub_id in sub_ids
        }

    @classmethod
    def check_lodgment_problems(cls, event, lodgements,
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
                n_("Too many reserve lodgers used."), lodgement_id,
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
                    ret.append((n_("Too few reserve lodgers used."),
                                lodgement_id, part_id, tuple(), 2))
                if num_reserve > lodgement['reserve']:
                    ret.append(_reserve_problem(lodgement_id, part_id))
                if _mixed(group) and any(
                        not registrations[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                if any(personas[registrations[reg_id]['persona_id']]['gender']
                       in (const.Genders.other, const.Genders.not_specified)
                       for reg_id in group):
                    ret.append((n_("Non-Binary Participant."), lodgement_id,
                                part_id,
                                tuple(reg_id for reg_id in group), 1))

        return ret

    @access("event")
    @event_guard()
    def lodgements(self, rs, event_id):
        """Overview of the lodgements of an event.

        This also displays some issues where possibly errors occured.
        """
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        inhabitants = self.calculate_groups(
            lodgements, rs.ambience['event'], registrations, key="lodgement_id")
        inhabitant_nums = {k: len(v) for k, v in inhabitants.items()}
        reserve_inhabitant_nums = {
            k: sum(
                1 for r in v if registrations[r]['parts'][k[1]]['is_reserve'])
            for k, v in inhabitants.items()}
        problems = self.check_lodgment_problems(
            rs.ambience['event'], lodgements, registrations, personas,
            inhabitants)
        problems_condensed = {}
        for lodgement_id, part_id in itertools.product(
                lodgement_ids, rs.ambience['event']['parts'].keys()):
            problems_here = [p for p in problems
                             if p[1] == lodgement_id and p[2] == part_id]
            problems_condensed[(lodgement_id, part_id)] = (
                max(p[4] for p in problems_here) if len(problems_here) else 0,
                "; ".join(rs.gettext(p[0]) for p in problems_here),)

        return self.render(rs, "lodgements", {
            'lodgements': lodgements,
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitant_nums,
            'reserve_inhabitants': reserve_inhabitant_nums,
            'problems': problems_condensed,
        })

    @access("event")
    @event_guard()
    def show_lodgement(self, rs, event_id, lodgement_id):
        """Display details of one lodgement."""
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in (self.eventproxy.get_registrations(rs, registration_ids)
                         .items())
            if any(part['lodgement_id'] == lodgement_id
                   for part in v['parts'].values())}
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), rs.ambience['event'], registrations,
            key="lodgement_id", personas=personas)

        problems = self.check_lodgment_problems(
            rs.ambience['event'], {lodgement_id: rs.ambience['lodgement']},
            registrations, personas, inhabitants)

        if not any(l for l in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        return self.render(rs, "show_lodgement", {
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,
        })

    @access("event")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs, event_id):
        """Render form."""
        return self.render(rs, "create_lodgement")

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def create_lodgement(self, rs, event_id, data):
        """Add a new lodgement."""
        data['event_id'] = event_id
        data = check(rs, "lodgement", data, creation=True)
        if rs.errors:
            return self.create_lodgement_form(rs, event_id)

        new_id = self.eventproxy.create_lodgement(rs, data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event")
    @event_guard(check_offline=True)
    def change_lodgement_form(self, rs, event_id, lodgement_id):
        """Render form."""
        field_values = {
            "fields.{}".format(key): value
            for key, value in rs.ambience['lodgement']['fields'].items()}
        merge_dicts(rs.values, rs.ambience['lodgement'], field_values)
        return self.render(rs, "change_lodgement")

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def change_lodgement(self, rs, event_id, lodgement_id, data):
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        data['id'] = lodgement_id
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(field['kind']))
            for field in rs.ambience['event']['fields'].values()
            if field['association'] == const.FieldAssociations.lodgement)
        raw_fields = request_extractor(rs, field_params)
        data['fields'] = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}
        data = check(rs, "lodgement", data)
        if rs.errors:
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
            rs.errors.append(("ack_delete", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_lodgement(rs, event_id, lodgement_id)

        code = self.eventproxy.delete_lodgement(rs, lodgement_id, cascade=True)
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
            part_id: sorted(
                (registration_id
                 for registration_id in registrations
                 if _check_without_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
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
            part_id: sorted(
                [{'name': (personas[registration['persona_id']]['given_names']
                           + " " + personas[registration['persona_id']]
                           ['family_name']),
                  'current': registration['parts'][part_id]['lodgement_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_lodgement(registration_id, part_id)],
                key=lambda x: (
                    x['current'] is not None,
                    name_key(personas[registrations[x['id']]['persona_id']]))
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
        if rs.errors:
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
            track_id: sorted(
                (registration_id
                 for registration_id in registrations
                 if _check_without_course(registration_id, track_id)),
                key=lambda anid: name_key(
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
            track_id: sorted(
                [{'name': (personas[registration['persona_id']]['given_names']
                           + " " + personas[registration['persona_id']]
                           ['family_name']),
                  'current': registration['tracks'][track_id]['course_id'],
                  'id': registration_id}
                 for registration_id, registration in registrations.items()
                 if _check_not_this_course(registration_id, track_id)],
                key=lambda x: (
                    x['current'] is not None,
                    name_key(personas[registrations[x['id']]['persona_id']]))
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
        if rs.errors:
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
        for part_id in event['parts']:
            spec["part{0}.status{0}".format(part_id)] = "int"
            spec["part{0}.lodgement_id{0}".format(part_id)] = "id"
            spec["part{0}.is_reserve{0}".format(part_id)] = "bool"
            for f in sorted(event['fields'].values(),
                            key=lambda f: f['field_name']):
                if f['association'] == const.FieldAssociations.lodgement:
                    temp = "lodge_fields{0}.xfield_{1}_{0}"
                    spec[temp.format(part_id, f['field_name'])] = f['kind']
            for track_id in event['parts'][part_id]['tracks']:
                spec["track{0}.course_id{0}".format(track_id)] = "id"
                spec["track{0}.course_instructor{0}".format(track_id)] = "id"
                spec["track{0}.is_course_instructor{0}".format(track_id)] \
                    = "bool"
                for f in sorted(event['fields'].values(),
                                key=lambda f: f['field_name']):
                    if f['association'] == const.FieldAssociations.course:
                        temp = "course_fields{0}.xfield_{1}_{0}"
                        spec[temp.format(track_id, f['field_name'])] = f['kind']
        if len(event['parts']) > 1:
            spec[",".join("part{0}.status{0}".format(part_id)
                          for part_id in event['parts'])] = "int"
            spec[",".join("part{0}.lodgement{0}".format(part_id)
                          for part_id in event['parts'])] = "id"
            spec[",".join("part{0}.is_reserve{0}".format(part_id)
                          for part_id in event['parts'])] = "bool"
            for f in sorted(event['fields'].values(),
                            key=lambda f: f['field_name']):
                if f['association'] == const.FieldAssociations.lodgement:
                    key = ",".join(
                        "lodge_fields{0}.xfield_{1}_{0}".format(
                            part_id, f['field_name'])
                        for part_id in event['parts'])
                    spec[key] = f['kind']
        if len(tracks) > 1:
            spec[",".join("track{0}.course_id{0}".format(track_id)
                          for track_id in tracks)] = "id"
            spec[",".join("track{0}.course_instructor{0}".format(track_id)
                          for track_id in tracks)] = "id"
            spec[",".join("track{0}.is_course_instructor{0}".format(track_id)
                          for track_id in tracks)] = "bool"
            for f in sorted(event['fields'].values(),
                            key=lambda f: f['field_name']):
                if f['association'] == const.FieldAssociations.course:
                    key = ",".join(
                        "course_fields{0}.xfield_{1}_{0}".format(
                            track_id, f['field_name'])
                        for track_id in tracks)
                    spec[key] = f['kind']
        for f in sorted(event['fields'].values(),
                        key=lambda f: f['field_name']):
            if f['association'] == const.FieldAssociations.registration:
                spec["reg_fields.xfield_{}".format(f['field_name'])] = f['kind']
        return spec

    @staticmethod
    def make_registration_query_aux(rs, event, courses,
                                    lodgements):
        """Un-inlined code to prepare input for template.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
        :type lodgements: {int: {str: object}}
        :rtype: ({str: dict}, {str: str})
        :returns: Choices for select inputs and titles for columns.
        """
        tracks = event['tracks']
        # First we construct the choices
        choices = {
            'persona.gender': OrderedDict(
                enum_entries_filter(const.Genders, rs.gettext))
        }
        lodgement_choices = OrderedDict(
            sorted(((lodgement_id, lodgement['moniker'])
                    for lodgement_id, lodgement in lodgements.items()),
                   key=operator.itemgetter(1)))
        for part_id in event['parts']:
            choices.update({
                "part{0}.status{0}".format(part_id):
                    OrderedDict(enum_entries_filter(
                        const.RegistrationPartStati, rs.gettext)),
                "part{0}.lodgement_id{0}".format(part_id): lodgement_choices,
            })
            choices.update({
                "lodge_fields{0}.xfield_{1}_{0}".format(
                    part_id, field['field_name']): OrderedDict(field['entries'])
                for field in event['fields'].values()
                if (field['association'] == const.FieldAssociations.lodgement
                    and field['entries'])})
        for track_id in tracks:
            course_choices = OrderedDict(
                (course_id, "{}. {}".format(courses[course_id]['nr'],
                                            courses[course_id]['shortname']))
                for course_id, course
                in xdictsort_filter(courses, 'nr', pad=True)
                if track_id in course['segments'])
            choices.update({
                "track{0}.course_id{0}".format(track_id):
                    course_choices,
                "track{0}.course_instructor{0}".format(track_id):
                    course_choices})
            key = "course_fields{0}.xfield_{1}_{0}"
            choices.update({
                key.format(track_id, field['field_name']):
                    OrderedDict(field['entries'])
                for field in event['fields'].values()
                if (field['association'] == const.FieldAssociations.course
                    and field['entries'])})
        if len(tracks) > 1:
            course_choices = OrderedDict(
                (course_id, "{}. {}".format(courses[course_id]['nr'],
                                            courses[course_id]['shortname']))
                for course_id, course
                in xdictsort_filter(courses, 'nr', pad=True))
            choices[",".join("track{0}.course_id{0}".format(track_id)
                             for track_id in tracks)] = course_choices
            choices[",".join("track{0}.course_instructor{0}".format(track_id)
                             for track_id in tracks)] = course_choices
        if len(event['parts']) > 1:
            choices.update({
                ",".join("part{0}.status{0}".format(part_id)
                         for part_id in event['parts']): OrderedDict(
                    enum_entries_filter(const.RegistrationPartStati,
                                        rs.gettext)),
                ",".join("part{0}.lodgement{0}".format(part_id)
                         for part_id in event['parts']): lodgement_choices,
            })
        choices.update({
            "reg_fields.xfield_{}".format(field['field_name']):
                OrderedDict(field['entries'])
            for field in event['fields'].values()
            if (field['association'] == const.FieldAssociations.registration
                and field['entries'])})

        # Second we construct the titles
        titles = {
            "reg_fields.xfield_{}".format(field['field_name']): field[
                'field_name']
            for field in event['fields'].values()
            if field['association'] == const.FieldAssociations.registration}
        if len(tracks) > 1:
            for track_id, track in tracks.items():
                titles.update({
                    "track{0}.course_id{0}".format(track_id): rs.gettext(
                        "{title}: course ").format(
                        title=track['title']),
                    "track{0}.course_instructor{0}".format(
                        track_id): rs.gettext(
                        "{title}: course instructor").format(
                        title=track['title']),
                    "track{0}.is_course_instructor{0}".format(track_id):
                        rs.gettext(
                            "{title}: instructs their course").format(
                            title=track['title']),
                })
                titles.update({
                    "course_fields{0}.xfield_{1}_{0}".format(
                        track_id, field['field_name']): rs.gettext(
                        "{title} course: {field}").format(
                        field=field['field_name'], title=track['title'])
                    for field in event['fields'].values()
                    if (field['association'] ==
                        const.FieldAssociations.course)
                })
            titles.update({
                ",".join("track{0}.course_id{0}".format(track_id)
                         for track_id in tracks): rs.gettext(
                    "any track: course"),
                ",".join("track{0}.course_instructor{0}".format(track_id)
                         for track_id in tracks): rs.gettext(
                    "any track: course instuctor"),
                ",".join("track{0}.is_course_instructor{0}".format(track_id)
                         for track_id in tracks): rs.gettext(
                    "any track: instructs their course"),
            })
            titles.update({
                ",".join("course_fields{0}.xfield_{1}_{0}".format(
                    track_id, field['field_name'])
                         for track_id in tracks): rs.gettext(
                    "any track course: {field}").format(
                    field=field['field_name'])
                for field in event['fields'].values()
                if field['association'] == const.FieldAssociations.course
            })
        elif len(tracks) == 1:
            track_id, track = next(iter(tracks.items()))
            titles.update({
                "track{0}.course_id{0}".format(track_id): rs.gettext("course"),
                "track{0}.course_instructor{0}".format(track_id):
                    rs.gettext("course instructor"),
                "track{0}.is_course_instructor{0}".format(track_id):
                    rs.gettext("instructs their course"),
            })
            titles.update({
                "course_fields{0}.xfield_{1}_{0}".format(
                    track_id, field['field_name']): rs.gettext(
                    "course: {field}").format(field=field['field_name'])
                for field in event['fields'].values()
                if field['association'] == const.FieldAssociations.course})
        if len(event['parts']) > 1:
            for part_id, part in event['parts'].items():
                titles.update({
                    "part{0}.status{0}".format(part_id): rs.gettext(
                        "{title}: registration status").format(
                        title=part['title']),
                    "part{0}.lodgement_id{0}".format(part_id): rs.gettext(
                        "{title}: lodgement").format(title=part['title']),
                    "part{0}.is_reserve{0}".format(part_id): rs.gettext(
                        "{title}: reserve lodger").format(title=part['title']),
                })
                titles.update({
                    "lodge_fields{0}.xfield_{1}_{0}".format(
                        part_id, field['field_name']): rs.gettext(
                        "{title} lodgement: {field}").format(
                        field=field['field_name'], title=part['title'])
                    for field in event['fields'].values()
                    if field['association'] == const.FieldAssociations.lodgement
                })
            titles.update({
                ",".join("part{0}.status{0}".format(part_id)
                         for part_id in event['parts']): rs.gettext(
                    "any part: registration status"),
                ",".join("part{0}.lodgement{0}".format(part_id)
                         for part_id in event['parts']): rs.gettext(
                    "any part: lodgement"),
                ",".join("part{0}.is_reserve{0}".format(part_id)
                         for part_id in event['parts']): rs.gettext(
                    "any part: reserve lodger")})
            titles.update({
                ",".join("lodge_fields{0}.xfield_{1}_{0}".format(
                    part_id, field['field_name'])
                         for part_id in event['parts']): rs.gettext(
                    "any part lodgement: {field}").format(
                    field=field['field_name'])
                for field in event['fields'].values()
                if field['association'] == const.FieldAssociations.lodgement
            })
        elif len(event['parts']) == 1:
            part_id, part = next(iter(event['parts'].items()))
            titles.update({
                "part{0}.status{0}".format(part_id):
                    rs.gettext("registration status"),
                "part{0}.lodgement_id{0}".format(part_id):
                    rs.gettext("lodgement"),
                "part{0}.is_reserve{0}".format(part_id):
                    rs.gettext("reserve lodger"),
            })
            titles.update({
                "lodge_fields{0}.xfield_{1}_{0}".format(
                    part_id, field['field_name']): rs.gettext(
                    "lodgement: {field}").format(field=field['field_name'])
                for field in event['fields'].values()
                if field['association'] == const.FieldAssociations.lodgement})
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
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None

        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        choices, titles = self.make_registration_query_aux(
            rs, rs.ambience['event'], courses, lodgements)
        choices_lists = {k: list(v.items()) for k, v in choices.items()}
        has_registrations = self.eventproxy.has_registrations(rs, event_id)

        default_queries = \
            self.conf.DEFAULT_QUERIES_REGISTRATION(rs.ambience['event'], spec)

        params = {
            'spec': spec, 'choices': choices, 'choices_lists': choices_lists,
            'query': query, 'default_queries': default_queries,
            'titles': titles, 'has_registrations': has_registrations,
        }
        # Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_registration"
            result = self.eventproxy.submit_general_query(rs, query,
                                                          event_id=event_id)
            params['result'] = result
            if download:
                fields = []
                for csvfield in query.fields_of_interest:
                    for field in csvfield.split(','):
                        fields.append(field.split('.')[-1])
                if download == "csv":
                    csv_data = csv_output(result, fields, substitutions=choices)
                    return self.send_file(
                        rs, data=csv_data, inline=False,
                        filename=rs.gettext("result.csv"))
                elif download == "json":
                    json_data = query_result_to_json(result, fields,
                                                     substitutions=choices)
                    return self.send_file(
                        rs, data=json_data, inline=False,
                        filename=rs.gettext("result.json"))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "registration_query", params)

    @access("event")
    @event_guard(check_offline=True)
    def checkin_form(self, rs, event_id):
        """Render form."""
        today = now().date()
        for part_id, part in rs.ambience['event']['parts'].items():
            if part['part_begin'] <= today <= part['part_end']:
                current_part = part_id
                if part['part_end'] > today:
                    break
        else:
            current_part = None
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in (self.eventproxy.get_registrations(rs, registration_ids)
                         .items())
            if (not v['checkin']
                and (not current_part or const.RegistrationPartStati(
                    v['parts'][current_part]['status']).is_present()))}
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                rs.ambience['event']['begin'])
        return self.render(rs, "checkin", {
            'registrations': registrations, 'personas': personas,
            'lodgements': lodgements})

    @access("event", modi={"POST"})
    @REQUESTdata(("registration_id", "id"))
    @event_guard(check_offline=True)
    def checkin(self, rs, event_id, registration_id):
        """Check a participant in."""
        if rs.errors:
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
        if rs.errors:
            return self.render(rs, "field_set_select")
        if field_id is None:
            registrations = self.eventproxy.get_registrations(rs, reg_ids)
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
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
    def field_set_form(self, rs, event_id, field_id, reg_ids):
        """Render form."""
        if field_id not in rs.ambience['event']['fields']:
            # also catches field_id validation errors
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
        ordered = sorted(
            registrations.keys(),
            key=lambda anid: name_key(
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
            # also catches field_id validation errors
            return werkzeug.exceptions.NotFound(n_("Wrong associated event."))
        field = rs.ambience['event']['fields'][field_id]
        if field['association'] != const.FieldAssociations.registration:
            return werkzeug.exceptions.NotFound(n_("Wrong associated field."))
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        kind = "{}_or_None".format(field['kind'])
        data_params = tuple(("input{}".format(registration_id), kind)
                            for registration_id in registration_ids)
        data = request_extractor(rs, data_params)
        if rs.errors:
            return self.field_set_form(rs, event_id, field_id, reg_ids)

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
        return self.redirect(rs, "event/registration_query")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs, event_id):
        """Lock an event for offline usage."""
        code = self.eventproxy.lock_event(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTfile("json")
    def unlock_event(self, rs, event_id, json):
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        data = check(rs, "serialized_event_upload", json)
        if rs.errors:
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
    @REQUESTdata(("ack_archive", "bool"))
    @event_guard(check_offline=True)
    def archive_event(self, rs, event_id, ack_archive):
        """Make a past_event from an event.

        This is at the boundary between event and cde frontend, since
        the past-event stuff generally resides in the cde realm.
        """
        if rs.ambience['event']['is_archived']:
            rs.notify("warning", n_("Event already archived."))
            return self.redirect(rs, "event/show_event")
        if not ack_archive:
            rs.errors.append(
                ("ack_conclude", ValueError(n_("Must be checked."))))
        if rs.errors:
            return self.show_event(rs, event_id)
        new_ids, message = self.pasteventproxy.archive_event(rs, event_id)
        if not new_ids:
            rs.notify("warning", message)
            return self.redirect(rs, "event/show_event")
        rs.notify("success", n_("Event archived."))
        if len(new_ids) == 1:
            return self.redirect(rs, "cde/show_past_event",
                                 {'pevent_id': unwrap(new_ids)})
        else:
            rs.notify("info", n_("Created multiple past events."))
            return self.redirect(rs, "event/show_event")

    @access("event_admin")
    @REQUESTdata(("codes", "[int]"), ("event_id", "id_or_None"),
                 ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"))
    def view_log(self, rs, codes, event_id, start, stop):
        """View activities concerning events organized via DB."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.eventproxy.retrieve_log(rs, codes, event_id, start, stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        event_ids = {entry['event_id'] for entry in log if entry['event_id']}
        events = self.eventproxy.get_events(rs, event_ids)
        all_events = self.eventproxy.list_db_events(rs)
        return self.render(rs, "view_log", {
            'log': log, 'personas': personas, 'events': events,
            'all_events': all_events})

    @access("event")
    @event_guard()
    @REQUESTdata(("codes", "[int]"), ("start", "non_negative_int_or_None"),
                 ("stop", "non_negative_int_or_None"))
    def view_event_log(self, rs, event_id, codes, start, stop):
        """View activities concerning one event organized via DB."""
        start = start or 0
        stop = stop or 50
        # no validation since the input stays valid, even if some options
        # are lost
        log = self.eventproxy.retrieve_log(rs, codes, event_id, start, stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_event_log", {
            'log': log, 'personas': personas,
        })
