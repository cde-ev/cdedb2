#!/usr/bin/env python3

"""Services for the event realm."""

from collections import OrderedDict
import copy
import csv
import itertools
import logging
import os
import os.path
import re
import shutil
import tempfile

import werkzeug

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access,
    check_validation as check, event_guard,
    REQUESTfile, request_data_extractor, cdedbid_filter)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input, Query
from cdedb.common import (
    name_key, merge_dicts, determine_age_class, deduct_years, AgeClasses,
    unwrap, now, ProxyShim, json_serialize)
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
import cdedb.database.constants as const
from cdedb.database.connection import Atomizer

class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    logger = logging.getLogger(__name__)
    user_management = {
        "persona_getter": lambda obj: obj.coreproxy.get_event_user,
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(EventBackend(configpath))
        self.pasteventproxy = ProxyShim(PastEventBackend(configpath))

    def finalize_session(self, rs):
        super().finalize_session(rs)
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

    @staticmethod
    def is_open(event_data):
        """Small helper to determine if an event is open for registration.

        This is a somewhat verbose condition encapsulated here for brevity.

        :type event_data: {str: object}
        :param event_data: event dataset as returned by the backend
        :rtype: bool
        """
        today = now().date()
        return (event_data['registration_start']
                and event_data['registration_start'] <= today
                and (event_data['registration_hard_limit'] is None
                     or event_data['registration_hard_limit'] >= today))

    def is_locked(self, event_data):
        """Shorthand to deremine locking state of an event.

        :type event_data: {str: object}
        :rtype: bool
        """
        return event_data['offline_lock'] != self.conf.CDEDB_OFFLINE_DEPLOYMENT

    @staticmethod
    def event_has_field(event_data, field):
        """Shorthand to check whether a field with given name is defined for
        an event.

        :type event_data: {str: object}
        :type field: str
        :rtype: bool
        """
        return any(fdata['field_name'] == field
                   for fdata in event_data['fields'].values())

    @access("persona")
    def index(self, rs):
        """Render start page."""
        open_events = self.eventproxy.list_open_events(rs)
        orga_events = self.eventproxy.get_event_data(rs, rs.user.orga)
        return self.render(rs, "index", {
            'open_events': open_events, 'orga_events': orga_events})

    @access("event_admin")
    def admin_change_user_form(self, rs, persona_id):
        return super().admin_change_user_form(rs, persona_id)

    @access("event_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "cloud_account", "notes")
    def admin_change_user(self, rs, persona_id, generation, change_note, data):
        return super().admin_change_user(rs, persona_id, generation,
                                         change_note, data)

    @access("event_admin")
    def create_user_form(self, rs):
        defaults = {
            'is_member': False,
            'bub_search': False,
            'cloud_account': False,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("event_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "gender", "birthday", "username", "telephone",
        "mobile", "address", "address_supplement", "postal_code",
        "location", "country", "cloud_account", "notes")
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

    @access("anonymous")
    @REQUESTdata(("secret", "str"))
    def genesis_form(self, rs, case_id, secret):
        return super().genesis_form(rs, case_id, secret=secret)

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict(
        "title", "name_supplement", "display_name", "birthday", "gender",
        "telephone", "mobile", "address", "address_supplement",
        "postal_code", "location", "country")
    def genesis(self, rs, case_id, secret, data):
        data.update({
            'is_active': True,
            'cloud_account': False,
            'notes': '',
        })
        return super().genesis(rs, case_id, secret=secret, data=data)

    @access("event_admin")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    def user_search(self, rs, CSV, is_search):
        """Perform search."""
        spec = QUERY_SPECS['qview_event_user']
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None
        events = self.pasteventproxy.list_past_events(rs)
        choices = {'pevent_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_event_user']
        params = {
            'spec': spec, 'choices': choices,
            'default_queries': default_queries, 'query': query}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_event_user"
            result = self.eventproxy.submit_general_query(rs, query)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("event_admin")
    def list_db_events(self, rs):
        """List all events organized via DB."""
        events = self.eventproxy.list_db_events(rs)
        data = self.eventproxy.get_event_data(rs, events.keys())
        return self.render(rs, "list_db_events", {'data': data})

    @access("event")
    def show_event(self, rs, event_id):
        """Display event organized via DB."""
        rs.ambience['event']['is_open'] = self.is_open(rs.ambience['event'])
        params = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            params['orgas'] = self.coreproxy.get_personas(
                rs, rs.ambience['event']['orgas'])
            params['institutions'] = self.pasteventproxy.list_institutions(rs)
            params['minor_form_present'] = os.path.isfile(os.path.join(
                self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        return self.render(rs, "show_event", params)

    @access("event")
    def course_list(self, rs, event_id):
        """List courses from an event."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        event_data['is_open'] = self.is_open(event_data)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        if courses:
            course_data = self.eventproxy.get_course_data(rs, courses.keys())
        else:
            course_data = None
        return self.render(rs, "course_list", {
            'event_data': event_data, 'course_data': course_data,})

    @access("event")
    @event_guard(check_offline=True)
    def change_event_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        institutions = self.pasteventproxy.list_institutions(rs)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_event", {
            'data': data, 'institutions': institutions})

    @access("event", modi={"POST"})
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "use_questionnaire", "notes")
    @event_guard(check_offline=True)
    def change_event(self, rs, event_id, data):
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, "event_data", data)
        if rs.errors:
            return self.change_event_form(rs, event_id)
        code = self.eventproxy.set_event_data(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    def get_minor_form(self, rs, event_id):
        """Retrieve minor form."""
        path = os.path.join(self.conf.STORAGE_DIR, "minor_form", str(event_id))
        return self.send_file(
            rs, mimetype="application/pdf",
            filename=self.i18n("minor_form.pdf", rs.lang), path=path)

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
        path = os.path.join(self.conf.STORAGE_DIR, 'minor_form', str(event_id))
        with open(path, 'wb') as f:
            f.write(minor_form)
        rs.notify("success", "Form updated.")
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @REQUESTdata(("orga_id", "cdedbid"))
    @event_guard(check_offline=True)
    def add_orga(self, rs, event_id, orga_id):
        """Make an additional persona become orga."""
        if rs.errors:
            return self.show_event(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] | {orga_id}
        }
        code = self.eventproxy.set_event_data(rs, newdata)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @REQUESTdata(("orga_id", "id"))
    @event_guard(check_offline=True)
    def remove_orga(self, rs, event_id, orga_id):
        """Demote a persona.

        This can drop your own orga role.
        """
        if rs.errors:
            return self.show_event(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] - {orga_id}
        }
        code = self.eventproxy.set_event_data(rs, newdata)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event")
    @event_guard()
    def part_summary_form(self, rs, event_id):
        """Render form."""
        current = {
            "{}_{}".format(key, part_id): value
            for part_id, part in rs.ambience['event']['parts'].items()
            for key, value in part.items() if key != 'id'}
        merge_dicts(rs.values, current)
        is_referenced = set()
        reg_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, reg_ids)
        for registration in registrations.values():
            is_referenced.update(registration['parts'].keys())
            is_referenced.update(registration['choices'].keys())
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_course_data(rs, course_ids)
        for course in courses.values():
            is_referenced.update(course['parts'])
        return self.render(rs, "part_summary", {'is_referenced': is_referenced})

    @staticmethod
    def process_part_input(rs, parts):
        """This handles input to configure the parts.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type parts: [int]
        :param parts: ids of parts
        :rtype: {int: {str: object}}
        """
        delete_flags = request_data_extractor(
            rs, (("delete_{}".format(part_id), "bool") for part_id in parts))
        deletes = {part_id for part_id in parts
                   if delete_flags['delete_{}'.format(part_id)]}
        spec = {
            'title': "str",
            'part_begin': "date",
            'part_end': "date",
            'fee': "decimal",
        }
        params = tuple(("{}_{}".format(key, part_id), value)
                       for part_id in parts if part_id not in deletes
                       for key, value in spec.items())
        data = request_data_extractor(rs, params)
        ret  = {
            part_id: {key: data["{}_{}".format(key, part_id)] for key in spec}
            for part_id in parts if part_id not in deletes
        }
        for part_id in deletes:
            ret[part_id] = None
        marker = 1
        while marker < 2**10:
            will_create = unwrap(request_data_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_data_extractor(rs, params)
                ret[-marker] = {key: data["{}_-{}".format(key, marker)]
                                for key in spec}
            else:
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        return ret

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def part_summary(self, rs, event_id):
        """Manipulate the parts of an event."""
        parts = self.process_part_input(
            rs, rs.ambience['event']['parts'].keys())
        if rs.errors:
            return self.part_summary_form(rs, event_id)
        for part_id, part in rs.ambience['event']['parts'].items():
            if parts.get(part_id) == part:
                ## remove unchanged
                del parts[part_id]
        event = {
            'id': event_id,
            'parts': parts
        }
        code = self.eventproxy.set_event_data(rs, event)
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
        delete_flags = request_data_extractor(
            rs, (("delete_{}".format(field_id), "bool") for field_id in fields))
        deletes = {field_id for field_id in fields
                   if delete_flags['delete_{}'.format(field_id)]}
        ret = {}
        params = lambda anid: (("kind_{}".format(anid), "str"),
                               ("entries_{}".format(anid), "str_or_None"))
        for field_id in fields:
            if field_id not in deletes:
                tmp = request_data_extractor(rs, params(field_id))
                temp = {}
                temp['kind'] = tmp["kind_{}".format(field_id)]
                temp['entries'] = tmp["entries_{}".format(field_id)]
                temp = check(rs, "event_field_data", temp)
                if temp:
                    ret[field_id] = temp
        for field_id in deletes:
            ret[field_id] = None
        marker = 1
        params = lambda anid: (("field_name_-{}".format(anid), "str"),
                               ("kind_-{}".format(anid), "str"),
                               ("entries_-{}".format(anid), "str_or_None"))
        while marker < 2**10:
            will_create = unwrap(request_data_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                tmp = request_data_extractor(rs, params(marker))
                temp = {}
                temp['field_name'] = tmp["field_name_-{}".format(marker)]
                temp['kind'] = tmp["kind_-{}".format(marker)]
                temp['entries'] = tmp["entries_-{}".format(marker)]
                temp = check(rs, "event_field_data", temp, creation=True)
                if temp:
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
                ## remove unchanged
                del fields[field_id]
        event = {
            'id': event_id,
            'fields': fields
        }
        code = self.eventproxy.set_event_data(rs, event)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/field_summary_form")

    @access("event_admin")
    def create_event_form(self, rs):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        return self.render(rs, "create_event", {'institutions': institutions})

    @access("event_admin", modi={"POST"})
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "use_questionnaire", "notes",
        "orga_ids")
    def create_event(self, rs, data):
        """Create a new event organized via DB."""
        if data['orga_ids'] is not None:
            data['orgas'] = {check(rs, "cdedbid", x.strip(), "orga_ids")
                             for x in data['orga_ids'].split(",")}
        del data['orga_ids']
        data = check(rs, "event_data", data, creation=True)
        if rs.errors:
            return self.create_event_form(rs)
        new_id = self.eventproxy.create_event(rs, data)
        # TODO create mailing lists
        self.notify_return_code(rs, new_id, success="Event created.")
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event")
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        params = {'event_data': event_data, 'course_data': course_data,}
        if event_id in rs.user.orga or self.is_admin(rs):
            registrations = self.eventproxy.list_registrations(rs, event_id)
            registration_data = {
                k: v for k, v in self.eventproxy.get_registrations(
                    rs, registrations).items()
                if any(pdata['course_id'] == course_id
                       or pdata['course_instructor'] == course_id
                       for pdata in v['parts'].values())}
            persona_data = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registration_data.values()))
            attendees = self.calculate_groups(
                (course_id,), event_data, registration_data, key="course_id",
                persona_data=persona_data)
            params['persona_data'] = persona_data
            params['registration_data'] = registration_data
            params['attendees'] = attendees
        return self.render(rs, "show_course", params)

    @access("event")
    @event_guard(check_offline=True)
    def change_course_form(self, rs, event_id, course_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        if event_id != course_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        if 'parts' not in rs.values:
            rs.values.setlist('parts', course_data['parts'])
        merge_dicts(rs.values, course_data)
        return self.render(rs, "change_course", {'event_data': event_data,
                                                 'course_data': course_data})

    @access("event", modi={"POST"})
    @REQUESTdata(("parts", "[int]"))
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "notes")
    @event_guard(check_offline=True)
    def change_course(self, rs, event_id, course_id, parts, data):
        """Modify a course associated to an event organized via DB."""
        data['id'] = course_id
        data['parts'] = parts
        data = check(rs, "course_data", data)
        if rs.errors:
            return self.change_course_form(rs, event_id, course_id)
        code = self.eventproxy.set_course_data(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @access("event")
    @event_guard(check_offline=True)
    def create_course_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        ## by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', data['parts'])
        return self.render(rs, "create_course", {'data': data})

    @access("event", modi={"POST"})
    @REQUESTdata(("parts", "[int]"))
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "notes")
    @event_guard(check_offline=True)
    def create_course(self, rs, event_id, parts, data):
        """Create a new course associated to an event organized via DB."""
        data['event_id'] = event_id
        data['parts'] = parts
        data = check(rs, "course_data", data, creation=True)
        if rs.errors:
            return self.create_course_form(rs, event_id)
        new_id = self.eventproxy.create_course(rs, data)
        self.notify_return_code(rs, new_id, success="Course created.")
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event")
    @event_guard()
    def stats(self, rs, event_id):
        """Present an overview of the basic stats."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        user_data = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        stati = const.RegistrationPartStati
        get_age = lambda udata: determine_age_class(
            udata['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        tests = OrderedDict((
            ('total', (lambda edata, rdata, pdata: (
                pdata['status'] != stati.not_applied))),
            ('pending', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.applied))),
            ('participant', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant))),
            (' u18', (lambda edata, rdata, pdata: (
                (pdata['status'] == stati.participant)
                and (get_age(user_data[rdata['persona_id']])
                     == AgeClasses.u18)))),
            (' u16', (lambda edata, rdata, pdata: (
                (pdata['status'] == stati.participant)
                and (get_age(user_data[rdata['persona_id']])
                     == AgeClasses.u16)))),
            (' u14', (lambda edata, rdata, pdata: (
                (pdata['status'] == stati.participant)
                and (get_age(user_data[rdata['persona_id']])
                     == AgeClasses.u14)))),
            (' checked in', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and rdata['checkin']))),
            (' not checked in', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and not rdata['checkin']))),
            (' orgas', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and rdata['persona_id'] in edata['orgas']))),
            (' instructors', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and pdata['course_id'] == pdata['course_instructor']))),
            (' attendees', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and pdata['course_id'] != pdata['course_instructor']))),
            (' first choice', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and len(rdata['choices'][pdata['part_id']]) > 0
                and (rdata['choices'][pdata['part_id']][0]
                     == pdata['course_id'])))),
            (' second choice', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and len(rdata['choices'][pdata['part_id']]) > 1
                and (rdata['choices'][pdata['part_id']][1]
                     == pdata['course_id'])))),
            (' third choice', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and len(rdata['choices'][pdata['part_id']]) > 2
                and (rdata['choices'][pdata['part_id']][2]
                     == pdata['course_id'])))),
            ('waitlist', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.waitlist))),
            ('guest', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.guest))),
            ('cancelled', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.cancelled))),
            ('rejected', (lambda edata, rdata, pdata: (
                pdata['status'] == stati.rejected))),))
        if not courses:
            for key in (' instructors', ' attendees', ' first choice',
                        ' second choice', ' third choice'):
                del tests[key]
        statistics = OrderedDict()
        for key, test in tests.items():
            statistics[key] = {
                part_id: sum(
                    1 for rdata in registration_data.values()
                    if test(event_data, rdata, rdata['parts'][part_id]))
                for part_id in event_data['parts']}
        tests2 = {
            'not payed': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_involved()
                and not rdata['payment'])),
            'pending': (lambda edata, rdata, pdata: (
                pdata['status'] == stati.applied
                and rdata['payment'])),
            'no parental agreement': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_involved()
                and get_age(user_data[rdata['persona_id']]).is_minor()
                and not rdata['parental_agreement'])),
            'no lodgement': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_present()
                and not pdata['lodgement_id'])),
            'no course': (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and not pdata['course_id']
                and rdata['persona_id'] not in edata['orgas'])),
            'wrong choice': (lambda edata, rdata, pdata: (
                pdata['status'] == stati.participant
                and pdata['course_id']
                and (pdata['course_id']
                     not in rdata['choices'][pdata['part_id']]))),
        }
        sorter = lambda registration_id: name_key(
            user_data[registration_data[registration_id]['persona_id']])
        listings = {
            key: {
                part_id: sorted(
                    (registration_id
                     for registration_id, rdata in registration_data.items()
                     if test(event_data, rdata, rdata['parts'][part_id])),
                    key=sorter)
                for part_id in event_data['parts']
            }
            for key, test in tests2.items()
        }
        return self.render(rs, "stats", {
            'event_data': event_data, 'registration_data': registration_data,
            'user_data': user_data, 'courses': courses,
            'statistics': statistics, 'listings': listings})

    @access("event")
    @REQUESTdata(("course_id", "id_or_None"), ("part_id", "id_or_None"),
                 ("position", "enum_coursefilterpositions_or_None"))
    @event_guard()
    def course_choices_form(self, rs, event_id, course_id, part_id, position):
        """Provide an overview of course choices.

        This allows flexible filtering of the displayed registrations.
        """
        if rs.errors:
            return self.show_event(rs, event_id)
        registration_ids = self.eventproxy.registrations_by_course(
            rs, event_id, course_id, part_id, position)
        registrations = self.eventproxy.get_registrations(
            rs, registration_ids.keys())
        personas = self.coreproxy.get_personas(rs, registration_ids.values())
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_course_data(rs, course_ids)

        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
        course_infos = {}
        stati = const.RegistrationPartStati
        for course_id, course in courses.items():
            for part_id in rs.ambience['event']['parts']:
                assigned = sum(1
                    for reg in all_regs.values()
                    if reg['parts'][part_id]['status'] == stati.participant
                    and reg['parts'][part_id]['course_id'] == course_id)
                all_instructors = sum(1
                    for reg in all_regs.values()
                    if reg['parts'][part_id]['course_instructor'] == course_id)
                assigned_instructors = sum(1
                    for reg in all_regs.values()
                    if reg['parts'][part_id]['status'] == stati.participant
                    and reg['parts'][part_id]['course_id'] == course_id
                    and reg['parts'][part_id]['course_instructor'] == course_id)
                course_infos[(course_id, part_id)] = {
                    'assigned': assigned,
                    'all_instructors': all_instructors,
                    'assigned_instructors': assigned_instructors,
                    'is_happening': part_id in course['parts'],
                }
        return self.render(rs, "course_choices", {
            'courses': courses, 'personas': personas,
            'registrations': registrations, 'course_infos': course_infos})

    @access("event", modi={"POST"})
    @REQUESTdata(("registration_ids", "[int]"), ("part_ids", "[int]"),
                 ("action", "int"), ("course_id", "id_or_None"))
    @event_guard(check_offline=True)
    def course_choices(self, rs, event_id, registration_ids, part_ids, action,
                       course_id):
        """Manipulate course choices.

        Allow assignment of multiple people in multiple parts to one of
        their choices or a specific course.
        """
        if rs.errors:
            return self.course_choices_form(rs, event_id)

        registrations = None
        if action >= 0:
            registrations = self.eventproxy.get_registrations(
                rs, registration_ids)
        elif action == -1:
            pass
        else:
            rs.notify("warning", "No action taken.")

        code = 1
        for registration_id in registration_ids:
            tmp = {
                'id': registration_id,
                'parts': {}
            }
            for part_id in part_ids:
                if action >= 0:
                    choices = registrations[registration_id]['choices']
                    try:
                        choice = choices[part_id][action]
                    except IndexError:
                        rs.notify("error", "No choice available.")
                    else:
                        tmp['parts'][part_id] = {'course_id': choice}
                elif action == -1:
                    tmp['parts'][part_id] = {'course_id': course_id}
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
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        choice_counts = {
            course_id: {
                (part_id, i): sum(
                    1 for rdata in registration_data.values()
                    if (len(rdata['choices'][part_id]) > i
                        and rdata['choices'][part_id][i] == course_id
                        and (rdata['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and rdata['persona_id'] not in rs.ambience['event']['orgas']))
                for part_id in rs.ambience['event']['parts']
                for i in range(3)
            }
            for course_id in courses
        }
        assign_counts = {
            course_id: {
                part_id: sum(
                    1 for rdata in registration_data.values()
                    if (rdata['parts'][part_id]['course_id'] == course_id
                        and (rdata['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and rdata['persona_id'] not in rs.ambience['event']['orgas']))
                for part_id in rs.ambience['event']['parts']
            }
            for course_id in courses
        }
        return self.render(rs, "course_stats", {
            'course_data': course_data, 'choice_counts': choice_counts,
            'assign_counts': assign_counts})

    @access("event")
    @event_guard()
    def downloads(self, rs, event_id):
        """Offer documents like nametags for download."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        return self.render(rs, "downloads", {'event_data': event_data})

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_nametags(self, rs, event_id, runs):
        """Create nametags.

        You probably want to edit the provided tex file.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.coreproxy.get_event_users(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        for rdata in registration_data.values():
            rdata['age'] = determine_age_class(
                user_data[rdata['persona_id']]['birthday'],
                min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        tex = self.fill_template(rs, "tex", "nametags", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'course_data': course_data})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = os.path.join(tmp_dir, event_data['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "nametags.tex"), 'w') as f:
                f.write(tex)
            src = os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png")
            shutil.copy(src, os.path.join(work_dir, "aka-logo.png"))
            shutil.copy(src, os.path.join(work_dir, "orga-logo.png"))
            shutil.copy(src, os.path.join(work_dir, "minor-pictogram.png"))
            for course_id in course_data:
                shutil.copy(src, os.path.join(
                    work_dir, "logo-{}.png".format(course_id)))
            return self.serve_complex_latex_document(
                rs, tmp_dir, event_data['shortname'], "nametags.tex", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_puzzle(self, rs, event_id, runs):
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        counts = {
            course_id: {
                (part_id, i): sum(
                    1 for rdata in registration_data.values()
                    if (len(rdata['choices'][part_id]) > i
                        and rdata['choices'][part_id][i] == course_id
                        and (rdata['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and rdata['persona_id'] not in event_data['orgas']))
                for part_id in event_data['parts']
                for i in range(3)
            }
            for course_id in courses
        }
        tex = self.fill_template(rs, "tex", "course_puzzle", {
            'event_data': event_data, 'course_data': course_data,
            'counts': counts, 'registration_data': registration_data,
            'persona_data': persona_data})
        return self.serve_latex_document(rs, tex, "course_puzzle", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_puzzle(self, rs, event_id, runs):
        """Aggregate lodgement information.

        This can be printed and cut to help with distribution of
        participants. This make use of the fields 'lodge' and 'may_reserve'.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.coreproxy.get_event_users(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        for rdata in registration_data.values():
            rdata['age'] = determine_age_class(
                user_data[rdata['persona_id']]['birthday'],
                min(p['part_begin'] for p in event_data['parts'].values()))
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        lodge_present = any(fdata['field_name'] == "lodge"
                            for fdata in event_data['fields'].values())
        may_reserve_present = any(fdata['field_name'] == "may_reserve"
                                  for fdata in event_data['fields'].values())
        tex = self.fill_template(rs, "tex", "lodgement_puzzle", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'lodge_present': lodge_present,
            'may_reserve_present': may_reserve_present})
        return self.serve_latex_document(rs, tex, "lodgement_puzzle", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_lists(self, rs, event_id, runs):
        """Create lists to post to course rooms."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        attendees = self.calculate_groups(
            courses, event_data, registration_data, key="course_id",
            persona_data=persona_data)
        tex = self.fill_template(rs, "tex", "course_lists", {
            'event_data': event_data, 'course_data': course_data,
            'registration_data': registration_data,
            'persona_data': persona_data, 'attendees': attendees})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = os.path.join(tmp_dir, event_data['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "course_lists.tex"), 'w') as f:
                f.write(tex)
            for course_id in course_data:
                shutil.copy(
                    os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png"),
                    os.path.join(work_dir, "logo-{}.png".format(course_id)))
            return self.serve_complex_latex_document(
                rs, tmp_dir, event_data['shortname'], "course_lists.tex", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_lists(self, rs, event_id, runs):
        """Create lists to post to lodgements."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            lodgements, event_data, registration_data, key="lodgement_id",
            persona_data=persona_data)
        tex = self.fill_template(rs, "tex", "lodgement_lists", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data,
            'persona_data': persona_data, 'inhabitants': inhabitants})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = os.path.join(tmp_dir, event_data['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "lodgement_lists.tex"), 'w') as f:
                f.write(tex)
            shutil.copy(
                os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png"),
                os.path.join(work_dir, "aka-logo.png"))
            return self.serve_complex_latex_document(
                rs, tmp_dir, event_data['shortname'], "lodgement_lists.tex",
                runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_participant_list(self, rs, event_id, runs):
        """Create list to send to all participants."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = {
            k: v
            for k, v in self.eventproxy.get_registrations(
                rs, registrations).items()
            if any(pdata['status'] == const.RegistrationPartStati.participant
                   for pdata in v['parts'].values())}
        user_data = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        ordered = sorted(
            registration_data.keys(),
            key=lambda anid: name_key(
                user_data[registration_data[anid]['persona_id']]))
        tex = self.fill_template(rs, "tex", "participant_list", {
            'event_data': event_data, 'course_data': course_data,
            'registration_data': registration_data, 'user_data': user_data,
            'ordered': ordered})
        return self.serve_latex_document(rs, tex, "participant_list", runs)

    @access("event")
    @event_guard()
    def download_expuls(self, rs, event_id):
        """Create TeX-snippet for announcement in the ExPuls."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses)
        tex = self.fill_template(rs, "tex", "expuls", {
            'event_data': event_data, 'course_data': course_data})
        return self.send_file(rs, data=tex, inline=False,
                              filename=self.i18n("expuls.tex", rs.lang))

    @access("event")
    @event_guard()
    def download_export(self, rs, event_id):
        """Retrieve all data for this event to initialize an offline
        instance."""
        data = self.eventproxy.export_event(rs, event_id)
        json_data = json_serialize(data)
        return self.send_file(rs, data=json_data, inline=False,
                              filename=self.i18n("export_event.json", rs.lang))

    @access("event")
    def register_form(self, rs, event_id):
        """Render form."""
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if rs.user.persona_id in registrations.values():
            rs.notify("info", "Allready registered.")
            return self.redirect(rs, "event/registration_status")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not self.is_open(event_data):
            rs.notify("warning", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(event_data):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/show_event")
        user_data = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        if not minor_form_present and age.is_minor():
            rs.notify("info", "No minors may register.")
            return self.redirect(rs, "event/show_event")
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in course_data
                            if part_id in course_data[course_id]['parts'])
            for part_id in event_data['parts']}
        ## by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', event_data['parts'])
        return self.render(rs, "register", {
            'event_data': event_data, 'user_data': user_data, 'age': age,
            'course_data': course_data, 'course_choices': course_choices})

    @staticmethod
    def process_registration_input(rs, event_data, course_data, parts=None):
        """Helper to handle input by participants.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event.

        :type rs: :py:class:`FrontendRequestState`
        :type event_data: {str: object}
        :type course_data: {int: {str: object}}
        :type parts: [int] or None
        :param parts: If not None this specifies the ids of the parts this
          registration applies to (since you can apply for only some of the
          parts of an event and should not have to choose courses for the
          non-relevant parts this is important). If None the parts have to
          be provided in the input.
        :rtype: {str: object}
        :returns: registration data set
        """
        standard_params = (("mixed_lodging", "bool"), ("foto_consent", "bool"),
                           ("notes", "str_or_None"))
        if parts is None:
            standard_params += (("parts", "[int]"),)
        standard_data = request_data_extractor(rs, standard_params)
        if parts is not None:
            standard_data['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params = (("course_choice{}_{}".format(part_id, i), "id")
                         for part_id in standard_data['parts']
                         for i in range(3))
        choices = request_data_extractor(rs, choice_params)
        instructor_params = (
            ("course_instructor{}".format(part_id), "id_or_None")
            for part_id in standard_data['parts'])
        instructor = request_data_extractor(rs, instructor_params)
        if not standard_data['parts']:
            rs.errors.append(("parts",
                              ValueError("Must select at least one part.")))
        parts_with_courses = set()
        for part_id in standard_data['parts']:
            ## only check for course choices if there are courses to choose
            if any(part_id in c['parts'] for c in course_data.values()):
                parts_with_courses.add(part_id)
                cids = {choices["course_choice{}_{}".format(part_id, i)]
                        for i in range(3)}
                if len(cids) != 3:
                    rs.errors.extend(
                        ("course_choice{}_{}".format(part_id, i),
                         ValueError("Must choose three different courses."))
                        for i in range(3))
        if not standard_data['foto_consent']:
            rs.errors.append(("foto_consent", ValueError("Must consent.")))
        part_data = {
            part_id: {
                'course_instructor':
                    instructor.get("course_instructor{}".format(part_id)),
            }
            for part_id in event_data['parts']
        }
        if parts is None:
            for part_id in part_data:
                stati = const.RegistrationPartStati
                if part_id in standard_data['parts']:
                    part_data[part_id]['status'] = stati.applied
                else:
                    part_data[part_id]['status'] = stati.not_applied
        choice_data = {
            part_id: tuple(choices["course_choice{}_{}".format(part_id, i)]
                           for i in range(3))
            for part_id in parts_with_courses
        }
        registration_data = {
            'mixed_lodging': standard_data['mixed_lodging'],
            'foto_consent': standard_data['foto_consent'],
            'notes': standard_data['notes'],
            'parts': part_data,
            'choices': choice_data,
        }
        return registration_data

    @access("event", modi={"POST"})
    def register(self, rs, event_id):
        """Register for an event."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not self.is_open(event_data):
            rs.notify("error", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(event_data):
            rs.notify("error", "Event locked.")
            return self.redirect(rs, "event/show_event")
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        registration_data = self.process_registration_input(rs, event_data,
                                                            course_data)
        if rs.errors:
            return self.register_form(rs, event_id)
        registration_data['event_id'] = event_data['id']
        registration_data['persona_id'] = rs.user.persona_id
        user_data = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        if not minor_form_present and age.is_minor():
            rs.notify("error", "No minors may register.")
            return self.redirect(rs, "event/show_event")
        registration_data['mixed_lodging'] = (registration_data['mixed_lodging']
                                              and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration_data)
        fee = sum(event_data['parts'][part_id]['fee']
                  for part_id, entry in registration_data['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved())
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': 'Registered for event {}'.format(event_data['title'])},
            {'user_data': user_data, 'event_data': event_data, 'fee': fee,
             'age': age})
        self.notify_return_code(rs, new_id, success="Registered for event.")
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def registration_status(self, rs, event_id):
        """Present current state of own registration."""
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        user_data = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        fee = sum(event_data['parts'][part_id]['fee']
                  for part_id, entry in registration_data['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved())
        return self.render(rs, "registration_status", {
            'registration_data': registration_data, 'event_data': event_data,
            'user_data': user_data, 'age': age, 'course_data': course_data,
            'fee': fee})

    @access("event")
    def amend_registration_form(self, rs, event_id):
        """Render form."""
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if (event_data['registration_soft_limit'] and
                now().date() > event_data['registration_soft_limit']):
            rs.notify("warning", "Registration closed, no changes possible.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        user_data = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in course_data
                            if part_id in course_data[course_id]['parts'])
            for part_id in event_data['parts']}
        non_trivials = {}
        for part_id in registration_data['parts']:
            for i, choice in enumerate(
                    registration_data['choices'].get(part_id, [])):
                param = "course_choice{}_{}".format(part_id, i)
                non_trivials[param] = choice
        for part_id, entry in registration_data['parts'].items():
            param = "course_instructor{}".format(part_id)
            non_trivials[param] = entry['course_instructor']
        merge_dicts(rs.values, non_trivials, registration_data)
        return self.render(rs, "amend_registration", {
            'event_data': event_data, 'user_data': user_data, 'age': age,
            'course_data': course_data, 'course_choices': course_choices,
            'parts': registration_data['parts'],})

    @access("event", modi={"POST"})
    def amend_registration(self, rs, event_id):
        """Change information provided during registering.

        Participants are not able to change for which parts they applied on
        purpose. For this they have to communicate with the orgas.
        """
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if (event_data['registration_soft_limit'] and
                now().date() > event_data['registration_soft_limit']):
            rs.notify("error", "No changes allowed anymore.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("error", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        stored_data = self.eventproxy.get_registration(rs, registration_id)
        registration_data = self.process_registration_input(
            rs, event_data, course_data, parts=stored_data['parts'])
        if rs.errors:
            return self.amend_registration_form(rs, event_id)

        registration_data['id'] = registration_id
        user_data = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        registration_data['mixed_lodging'] = (registration_data['mixed_lodging']
                                              and age.may_mix())
        code = self.eventproxy.set_registration(rs, registration_data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/registration_status")

    @access("event")
    def questionnaire_form(self, rs, event_id):
        """Render form."""
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not event_data['use_questionnaire']:
            rs.notify("warning", "Questionnaire disabled.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("info", "Event locked.")
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        merge_dicts(rs.values, registration_data['field_data'])
        return self.render(rs, "questionnaire", {
            'event_data': event_data, 'questionnaire': questionnaire,})

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
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not event_data['use_questionnaire']:
            rs.notify("error", "Questionnaire disabled.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("error", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        f = lambda entry: event_data['fields'][entry['field_id']]
        params = tuple(
            (f(entry)['field_name'], "{}_or_None".format(f(entry)['kind']))
            for entry in questionnaire
            if entry['field_id'] and not entry['readonly'])
        data = request_data_extractor(rs, params)
        if rs.errors:
            return self.questionnaire_form(rs, event_id)

        code = self.eventproxy.set_registration(rs, {
            'id': registration_id, 'field_data': data,})
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
        return self.render(rs, "questionnaire_summary", {
            'questionnaire': questionnaire,})

    @staticmethod
    def process_questionnaire_input(rs, num):
        """This handles input to configure the questionnaire.

        Since this covers a variable number of rows, we cannot do this
        statically. This takes care of validation too.

        :type rs: :py:class:`FrontendRequestState`
        :type num: int
        :param num: number of rows to expect
        :rtype: [{str: object}]
        """
        delete_flags = request_data_extractor(
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
        data = request_data_extractor(rs, params)
        questionnaire = tuple(
            {key: data["{}_{}".format(key, i)] for key in spec}
            for i in range(num) if i not in deletes
        )
        marker = 1
        while marker < 2**10:
            will_create = unwrap(request_data_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_data_extractor(rs, params)
                questionnaire += ({key: data["{}_-{}".format(key, marker)]
                                   for key in spec},)
            else:
                break
            marker += 1
        rs.values['create_last_index'] = marker - 1
        return questionnaire

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def questionnaire_summary(self, rs, event_id):
        """Manipulate the questionnaire form.

        This allows the orgas to design a form without interaction with an
        administrator.
        """
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        new_questionnaire = self.process_questionnaire_input(
            rs, len(questionnaire))
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
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        return self.render(rs, "reorder_questionnaire", {
            'event_data': event_data, 'questionnaire': questionnaire})

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
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if event_id != registration_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        user_data = self.coreproxy.get_event_user(
            rs, registration_data['persona_id'])
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        return self.render(rs, "show_registration", {
            'registration_data': registration_data, 'event_data': event_data,
            'user_data': user_data, 'age': age, 'course_data': course_data,
            'lodgement_data': lodgement_data,})

    @access("event")
    @event_guard(check_offline=True)
    def change_registration_form(self, rs, event_id, registration_id):
        """Render form."""
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if event_id != registration_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        persona_data = self.coreproxy.get_persona(
            rs, registration_data['persona_id'])
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in course_data
                            if part_id in course_data[course_id]['parts'])
            for part_id in event_data['parts']}
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        reg_values = {"reg.{}".format(key): value
                      for key, value in registration_data.items()}
        part_values = []
        for part_id in registration_data['parts']:
            one_part = {
                "part{}.{}".format(part_id, key): value
                for key, value in registration_data['parts'][part_id].items()}
            for i, course_choice in enumerate(
                    registration_data['choices'].get(part_id, [])):
                key = 'part{}.course_choice_{}'.format(part_id, i)
                one_part[key] = course_choice
            part_values.append(one_part)
        field_values = {
            "fields.{}".format(key): value
            for key, value in registration_data['field_data'].items()}
        ## Fix formatting of ID
        reg_values['reg.real_persona_id'] = cdedbid_filter(
            reg_values['reg.real_persona_id'])
        merge_dicts(rs.values, reg_values, field_values, *part_values)
        return self.render(rs, "change_registration", {
            'registration_data': registration_data, 'event_data': event_data,
            'persona_data': persona_data, 'course_data': course_data,
            'course_choices': course_choices, 'lodgement_data': lodgement_data})

    @staticmethod
    def process_orga_registration_input(rs, event_data, do_fields=True):
        """Helper to handle input by orgas.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event. This puts less restrictions
        on the input (like not requiring three different course choices).

        :type rs: :py:class:`FrontendRequestState`
        :type event_data: {str: object}
        :rtype: {str: object}
        :returns: registration data set
        """
        reg_params = (
            ("reg.notes", "str_or_None"), ("reg.orga_notes", "str_or_None"),
            ("reg.payment", "date_or_None"), ("reg.parental_agreement", "bool"),
            ("reg.mixed_lodging", "bool"), ("reg.checkin", "date_or_None"),
            ("reg.foto_consent", "bool"),
            ("reg.real_persona_id", "cdedbid_or_None"))
        reg_data = request_data_extractor(rs, reg_params)
        part_params = []
        for part_id in event_data['parts']:
            prefix = "part{}".format(part_id)
            part_params.append(("{}.status".format(prefix),
                                "enum_registrationpartstati"))
            part_params.extend(
                ("{}.{}".format(prefix, suffix), "id_or_None")
                for suffix in ("course_id", "course_choice_0",
                               "course_choice_1", "course_choice_2",
                               "course_instructor", "lodgement_id"))
        part_data = request_data_extractor(rs, part_params)
        field_params = tuple(
            ("fields.{}".format(fdata['field_name']),
             "{}_or_None".format(fdata['kind']))
            for fdata in event_data['fields'].values())
        field_data = request_data_extractor(rs, field_params)

        new_parts = {
            part_id: {
                key: part_data["part{}.{}".format(part_id, key)]
                for key in ("status", "course_id", "course_instructor",
                            "lodgement_id")
            }
            for part_id in event_data['parts']
        }
        new_choices = {}
        for part_id in event_data['parts']:
            extractor = lambda i: part_data["part{}.course_choice_{}".format(
                part_id, i)]
            new_choices[part_id] = tuple(extractor(i)
                                         for i in range(3) if extractor(i))
        new_fields = {
            key.split('.', 1)[1]: value for key, value in field_data.items()}

        registration_data = {
            key.split('.', 1)[1]: value for key, value in reg_data.items()}
        registration_data['parts'] = new_parts
        registration_data['choices'] = new_choices
        if do_fields:
            registration_data['field_data'] = new_fields
        return registration_data

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def change_registration(self, rs, event_id, registration_id):
        """Make privileged changes to any information pertaining to a
        registration.

        Strictly speaking this makes a lot of the other functionality
        redundant (like managing the lodgement inhabitants), but it would be
        much more cumbersome to always use this interface.
        """
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if event_id != registration_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registration_data = self.process_orga_registration_input(rs, event_data)
        if rs.errors:
            return self.change_registration_form(rs, event_id, registration_id)

        registration_data['id'] = registration_id
        code = self.eventproxy.set_registration(rs, registration_data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_registration")

    @access("event")
    @event_guard(check_offline=True)
    def add_registration_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in course_data
                            if part_id in course_data[course_id]['parts'])
            for part_id in event_data['parts']}
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        return self.render(rs, "add_registration", {
            'event_data': event_data, 'course_data': course_data,
            'course_choices': course_choices,
            'lodgement_data': lodgement_data,})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def add_registration(self, rs, event_id):
        """Register a participant by an orga.

        This should not be used that often, since a registration should
        singnal legal consent which is not provided this way.
        """
        persona_id = unwrap(
            request_data_extractor(rs, (("user_data.persona_id", "cdedbid"),)))
        if (persona_id is not None
                and not self.coreproxy.verify_personas(
                    rs, (persona_id,), required_roles=("event",))):
            rs.errors.append(("user_data.persona_id",
                              ValueError("Invalid persona.")))
        if not rs.errors and self.eventproxy.list_registrations(
                rs, event_id, persona_id=persona_id):
            rs.errors.append(("user_data.persona_id",
                              ValueError("Allready registered.")))
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registration_data = self.process_orga_registration_input(
            rs, event_data, do_fields=False)
        if rs.errors:
            return self.add_registration_form(rs, event_id)

        registration_data['persona_id'] = persona_id
        registration_data['event_id'] = event_id
        new_id = self.eventproxy.create_registration(rs, registration_data)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

    @staticmethod
    def calculate_groups(entity_ids, event_data, registration_data, key,
                         persona_data=None):
        """Determine inhabitants/attendees of lodgements/courses.

        This has to take care only to select registrations which are
        actually present (and not cancelled or such).

        :type entity_ids: [int]
        :type event_data: {str: object}
        :type registration_data: {int: {str: object}}
        :type key: str
        :param key: one of lodgement_id or course_id, signalling what to do
        :type persona_data: {int: {str: object}} or None
        :param persona_data: If provided this is used to sort the resulting
          lists by name, so that the can be displayed sorted.
        :rtype: {(int, int): [int]}
        """
        def _check_belonging(entity_id, part_id, registration_id):
            """The actual check, un-inlined."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (
                pdata[key] == entity_id
                and const.RegistrationPartStati(pdata['status']).is_present())
        if persona_data is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: name_key(
                persona_data[registration_data[anid]['persona_id']])
        return {
            (entity_id, part_id): sorted(
                (registration_id for registration_id in registration_data
                 if _check_belonging(entity_id, part_id, registration_id)),
                key=sorter)
            for entity_id in entity_ids
            for part_id in event_data['parts']
        }

    @classmethod
    def check_lodgment_problems(cls, event_data, lodgement_data,
                                registration_data, user_data, inhabitants):
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        This makes use of the 'reserve' field.

        :type event_data: {str: object}
        :type lodgement_data: {int: {str: object}}
        :type registration_data: {int: {str: object}}
        :type user_data: {int: {str: object}}
        :type inhabitants: {(int, int): [int]}
        :rtype: [(str, int, int, [int])]
        :returns: problems as four tuples of (problem description, lodgement
          id, part id, affected registrations).
        """
        ret = []
        ## first some un-inlined code pieces (otherwise nesting is a bitch)
        def _mixed(group):
            """Un-inlined check whether both genders are present."""
            return any(
                user_data[registration_data[a]['persona_id']]['gender']
                != user_data[registration_data[b]['persona_id']]['gender']
                for a, b in itertools.combinations(group, 2))
        def _mixing_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for mixing problems."""
            return (
                "Mixed lodgement with non-mixing participants.",
                lodgement_id, part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if not registration_data[reg_id]['mixed_lodging']))
        def _reserve(group, part_id):
            """Un-inlined code to count the number of registrations assigned
            to a lodgement as reserve lodgers."""
            return sum(
                1 for reg_id in group
                if registration_data[reg_id]['field_data'].get(
                    'reserve_{}'.format(part_id)))
        def _reserve_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for reserve problems."""
            return (
                "Wrong number of reserve lodgers used.", lodgement_id, part_id,
                tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if registration_data[reg_id]['field_data'].get(
                        'reserve_{}'.format(part_id))))

        ## now the actual work
        for lodgement_id in lodgement_data:
            for part_id in event_data['parts']:
                group = inhabitants[(lodgement_id, part_id)]
                ldata = lodgement_data[lodgement_id]
                if len(group) > ldata['capacity'] + ldata['reserve']:
                    ret.append(("Overful lodgement.", lodgement_id, part_id,
                                tuple()))
                if _mixed(group) and any(
                        not registration_data[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                if (cls.event_has_field(event_data, 'reserve')
                        and (len(group) - ldata['capacity']
                             != _reserve(group, part_id))
                        and ((len(group) - ldata['capacity'] > 0)
                             or _reserve(group, part_id))):
                    ret.append(_reserve_problem(lodgement_id, part_id))
        return ret

    @access("event")
    @event_guard()
    def lodgements(self, rs, event_id):
        """Overview of the lodgements of an event.

        This also displays some issues where possibly errors occured.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            lodgements, event_data, registration_data, key="lodgement_id")

        problems = self.check_lodgment_problems(
            event_data, lodgement_data, registration_data, user_data,
            inhabitants)

        return self.render(rs, "lodgements", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants, 'problems': problems,})

    @access("event")
    @event_guard()
    def show_lodgement(self, rs, event_id, lodgement_id):
        """Display details of one lodgement."""
        # TODO check whether this is deletable
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        if lodgement_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = {
            k: v for k, v in self.eventproxy.get_registrations(
                rs, registrations).items()
            if any(pdata['lodgement_id'] == lodgement_id
                   for pdata in v['parts'].values())}
        user_data = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), event_data, registration_data, key="lodgement_id",
            persona_data=user_data)

        plural_data = {lodgement_id: lodgement_data}
        problems = self.check_lodgment_problems(
            event_data, plural_data, registration_data, user_data,
            inhabitants)

        if not any(l for l in inhabitants.values()):
            merge_dicts(rs.values, {'ack_delete': True})

        return self.render(rs, "show_lodgement", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants, 'problems': problems,})

    @access("event")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        return self.render(rs, "create_lodgement", {'event_data': event_data})

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def create_lodgement(self, rs, event_id, data):
        """Add a new lodgement."""
        data['event_id'] = event_id
        data = check(rs, "lodgement_data", data, creation=True)
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
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        if lodgement_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)

        merge_dicts(rs.values, lodgement_data)
        return self.render(rs, "change_lodgement", {
            'event_data': event_data, 'lodgement_data': lodgement_data,})

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def change_lodgement(self, rs, event_id, lodgement_id, data):
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        if lodgement_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        data['id'] = lodgement_id
        data = check(rs, "lodgement_data", data)
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
            rs.notify("error", "Not deleting a non-empty lodgement.")
            return self.redirect(rs, "event/show_lodgement")
        code = self.eventproxy.delete_lodgement(rs, lodgement_id, cascade=True)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/lodgements")

    @access("event")
    @event_guard(check_offline=True)
    def manage_inhabitants_form(self, rs, event_id, lodgement_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), event_data, registration_data, key="lodgement_id",
            persona_data=persona_data)
        def _check_without_lodgement(registration_id, part_id):
            """Un-inlined check for registration without lodgement."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(pdata['status']).is_present()
                    and not pdata['lodgement_id'])
        without_lodgement = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_without_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
                    persona_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        def _check_with_lodgement(registration_id, part_id):
            """Un-inlined check for registration with different lodgement."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(pdata['status']).is_present()
                    and pdata['lodgement_id']
                    and pdata['lodgement_id'] != lodgement_id)
        with_lodgement = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_with_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
                    persona_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        return self.render(rs, "manage_inhabitants", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data,
            'persona_data': persona_data, 'inhabitants': inhabitants,
            'without_lodgement': without_lodgement,
            'with_lodgement': with_lodgement})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs, event_id, lodgement_id):
        """Alter who is assigned to a lodgement.

        This tries to be a bit smart and write only changed state.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        params = tuple(("inhabitants_{}".format(part_id), "int_csv_list")
                       for part_id in event_data['parts'])
        data = request_data_extractor(rs, params)
        if rs.errors:
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        code = 1
        for registration_id, rdata in registration_data.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            for part_id in event_data['parts']:
                inhabits = (registration_id
                            in data["inhabitants_{}".format(part_id)])
                if (inhabits
                        != (lodgement_id
                            == rdata['parts'][part_id]['lodgement_id'])):
                    new_reg['parts'][part_id] = {
                        'lodgement_id': (lodgement_id if inhabits else None)
                    }
            if new_reg['parts']:
                code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_lodgement")

    @access("event")
    @event_guard(check_offline=True)
    def manage_attendees_form(self, rs, event_id, course_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        attendees = self.calculate_groups(
            (course_id,), event_data, registration_data, key="course_id",
            persona_data=persona_data)
        def _check_without_course(registration_id, part_id):
            """Un-inlined check for registration without course."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (pdata['status'] == const.RegistrationPartStati.participant
                    and not pdata['course_id'])
        without_course = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_without_course(registration_id, part_id)),
                key=lambda anid: name_key(
                    persona_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        def _check_with_course(registration_id, part_id):
            """Un-inlined check for registration with different course."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (pdata['status'] == const.RegistrationPartStati.participant
                    and pdata['course_id']
                    and pdata['course_id'] != course_id)
        with_course = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_with_course(registration_id, part_id)),
                key=lambda anid: name_key(
                    persona_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        return self.render(rs, "manage_attendees", {
            'event_data': event_data, 'course_data': course_data,
            'registration_data': registration_data,
            'persona_data': persona_data, 'attendees': attendees,
            'without_course': without_course, 'with_course': with_course})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_attendees(self, rs, event_id, course_id):
        """Alter who is assigned to this course."""
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        params = tuple(("attendees_{}".format(part_id), "int_csv_list")
                       for part_id in course_data['parts'])
        data = request_data_extractor(rs, params)
        if rs.errors:
            return self.manage_attendees_form(rs, event_id, course_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        code = 1
        for registration_id, rdata in registration_data.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            for part_id in course_data['parts']:
                attends = (registration_id
                           in data["attendees_{}".format(part_id)])
                if (attends
                        != (course_id == rdata['parts'][part_id]['course_id'])):
                    new_reg['parts'][part_id] = {
                        'course_id': (course_id if attends else None)
                    }
            if new_reg['parts']:
                code *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_course")

    @staticmethod
    def make_registration_query_spec(event_data):
        """Helper to enrich ``QUERY_SPECS['qview_registration']``.

        Since each event has dynamic columns for parts and extra fields we
        have amend the query spec on the fly.

        :type event_data: {str: object}
        """
        spec = copy.deepcopy(QUERY_SPECS['qview_registration'])
        ## note that spec is an ordered dict and we should respect the order
        for part_id in event_data['parts']:
            spec["part{0}.course_id{0}".format(part_id)] = "id"
            spec["part{0}.status{0}".format(part_id)] = "int"
            spec["part{0}.lodgement_id{0}".format(part_id)] = "id"
            spec["part{0}.course_instructor{0}".format(part_id)] = "id"
        spec[",".join("part{0}.course_id{0}".format(part_id)
                      for part_id in event_data['parts'])] = "id"
        spec[",".join("part{0}.status{0}".format(part_id)
                      for part_id in event_data['parts'])] = "int"
        spec[",".join("part{0}.lodgement{0}".format(part_id)
                      for part_id in event_data['parts'])] = "id"
        spec[",".join("part{0}.course_instructor{0}".format(part_id)
                      for part_id in event_data['parts'])] = "id"
        for e in sorted(event_data['fields'].values(),
                        key=lambda e: e['field_name']):
            spec["fields.{}".format(e['field_name'])] = e['kind']
        return spec

    @classmethod
    def make_registracion_query_aux(cls, rs, event_data, course_data,
                                    lodgement_data):
        """Un-inlined code to prepare input for template.

        :type rs: :py:class:`FrontendRequestState`
        :type event_data: {str: object}
        :type course_data: {int: {str: object}}
        :type lodgement_data: {int: {str: object}}
        :rtype: ({str: dict}, {str: str})
        :returns: Choices for select inputs and titles for columns.
        """
        choices = {'user_data.gender': cls.enum_choice(rs, const.Genders)}
        for part_id in event_data['parts']:
            choices.update({
                "part{0}.course_id{0}".format(part_id): {
                    course_id: cdata['title']
                    for course_id, cdata in course_data.items()
                    if part_id in cdata['parts']},
                "part{0}.status{0}".format(part_id): cls.enum_choice(
                    rs, const.RegistrationPartStati),
                "part{0}.lodgement_id{0}".format(part_id): {
                    lodgement_id: ldata['moniker']
                    for lodgement_id, ldata in lodgement_data.items()},
                "part{0}.course_instructor{0}".format(part_id): {
                    course_id: cdata['title']
                    for course_id, cdata in course_data.items()
                    if part_id in cdata['parts']},})
        choices.update({
            "fields.{}".format(fdata['field_name']): {
                value: desc for value, desc in fdata['entries']}
            for fdata in event_data['fields'].values() if fdata['entries']})

        titles = {
            "fields.{}".format(fdata['field_name']): fdata['field_name']
            for fdata in event_data['fields'].values()}
        for part_id, pdata in event_data['parts'].items():
            titles.update({
                "part{0}.course_id{0}".format(part_id): cls.i18n(
                    "course (part {})".format(pdata['title']), rs.lang),
                "part{0}.status{0}".format(part_id): cls.i18n(
                    "registration status (part {})".format(pdata['title']),
                    rs.lang),
                "part{0}.lodgement_id{0}".format(part_id): cls.i18n(
                    "lodgement (part {})".format(pdata['title']), rs.lang),
                "part{0}.course_instructor{0}".format(part_id): cls.i18n(
                    "course instructor (part {})".format(pdata['title']),
                    rs.lang),
            })
        titles.update({
            ",".join("part{0}.course_id{0}".format(part_id)
                     for part_id in event_data['parts']): cls.i18n(
                         "course (any part)", rs.lang),
            ",".join("part{0}.status{0}".format(part_id)
                     for part_id in event_data['parts']): cls.i18n(
                         "registration status (any part)", rs.lang),
            ",".join("part{0}.lodgement{0}".format(part_id)
                     for part_id in event_data['parts']): cls.i18n(
                         "lodgement (any part)", rs.lang),
            ",".join("part{0}.course_instructor{0}".format(part_id)
                     for part_id in event_data['parts']): cls.i18n(
                         "course instuctor (any part)", rs.lang)})

        return choices, titles

    @access("event")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    @event_guard()
    def registration_query(self, rs, event_id, CSV, is_search):
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        spec = self.make_registration_query_spec(event_data)
        ## mangle the input, so we can prefill the form
        query_input = mangle_query_input(rs, spec)
        if is_search:
            query = check(rs, "query_input", query_input, "query", spec=spec,
                          allow_empty=False)
        else:
            query = None

        courses = self.eventproxy.list_db_courses(rs, event_id)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        choices, titles = self.make_registracion_query_aux(
            rs, event_data, course_data, lodgement_data)
        default_queries = self.conf.DEFAULT_QUERIES['qview_registration']
        default_queries["all"] = Query(
            "qview_registration", spec,
            ("reg.id", "user_data.given_names", "user_data.family_name"),
            tuple(),
            (("reg.id", True),),)
        default_queries["minors"] = Query(
            "qview_registration", spec,
            ("reg.id", "user_data.given_names", "user_data.family_name",
             "birthday"),
            (("birthday", QueryOperators.greater,
              deduct_years(now().date(), 18)),),
            (("user_data.birthday", True), ("reg.id", True)),)
        params = {
            'spec': spec, 'choices': choices,
            'default_queries': default_queries, 'titles': titles,
            'event_data': event_data, 'query': query,}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_registration"
            result = self.eventproxy.submit_general_query(rs, query,
                                                          event_id=event_id)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result', params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "registration_query", params)

    @access("event", modi={"POST"})
    @REQUESTdata(("column", "str"), ("num_rows", "int"))
    @event_guard(check_offline=True)
    def registration_action(self, rs, event_id, column, num_rows):
        """Apply changes to a selection of registrations.

        This works in conjunction with the query method above.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        spec = self.make_registration_query_spec(event_data)
        ## The following should be safe, as there are no columns which
        ## forbid NULL and are settable this way. If the aforementioned
        ## sentence is wrong all we get is a validation error in the
        ## backend.
        value = unwrap(request_data_extractor(
            rs, (("value", "{}_or_None".format(spec[column])),)))
        selection_params = (("row_{}".format(i), "bool")
                            for i in range(num_rows))
        selection_data = request_data_extractor(rs, selection_params)
        id_params = (("row_{}_id".format(i), "int") for i in range(num_rows))
        id_data = request_data_extractor(rs, id_params)
        if rs.errors:
            return self.registration_query(rs, event_id, CSV=False,
                                           is_search=True)
        code = 1
        for i in range(num_rows):
            if selection_data["row_{}".format(i)]:
                new_data = {'id': id_data["row_{}_id".format(i)]}
                field = column.split('.', 1)[1]
                if column.startswith("part"):
                    mo = re.search(r"^part([0-9]+)\.([a-zA-Z_]+)[0-9]+$",
                                   column)
                    part_id = int(mo.group(1))
                    field = mo.group(2)
                    new_data['parts'] = {part_id: {field: value}}
                elif column.startswith("fields."):
                    new_data['field_data'] = {field: value}
                else:
                    new_data[field] = value
                code *= self.eventproxy.set_registration(rs, new_data)
        self.notify_return_code(rs, code)
        params = {key: value for key, value in rs.request.values.items()
                  if key.startswith(("qsel_", "qop_", "qval_", "qord_"))}
        params['CSV'] = False
        params['is_search'] = True
        return self.redirect(rs, "event/registration_query", params)

    @access("event")
    @event_guard(check_offline=True)
    def checkin_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        today = now().date()
        for part_id, pdata in event_data['parts'].items():
            if pdata['part_begin'] <= today and pdata['part_end'] >= today:
                current_part = part_id
                break
        else:
            current_part = None
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = {
            k: v for k, v in self.eventproxy.get_registrations(
                rs, registrations).items()
            if (not v['checkin']
                and (not current_part or const.RegistrationPartStati(
                    v['parts'][current_part]['status']).is_present()))}
        user_data = self.coreproxy.get_event_users(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        for rdata in registration_data.values():
            rdata['age'] = determine_age_class(
                user_data[rdata['persona_id']]['birthday'],
                min(p['part_begin'] for p in event_data['parts'].values()))
        return self.render(rs, "checkin", {
            'event_data': event_data, 'registration_data': registration_data,
            'user_data': user_data})

    @access("event", modi={"POST"})
    @REQUESTdata(("registration_id", "id"))
    @event_guard(check_offline=True)
    def checkin(self, rs, event_id, registration_id):
        """Check a participant in."""
        if rs.errors:
            return self.checkin_form(rs, event_id)
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if registration_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        if registration_data['checkin']:
            rs.notify("warning", "Allready checked in.")
            return self.checkin_form(rs, event_id)

        new_reg = {
            'id': registration_id,
            'checkin': now(),
        }
        code = self.eventproxy.set_registration(rs, new_reg)
        self.notify_return_code(rs, code)
        return self.checkin_form(rs, event_id)

    @access("event")
    @REQUESTdata(("field_id", "id_or_None"))
    @event_guard(check_offline=True)
    def field_set_select(self, rs, event_id, field_id):
        """Select a field for manipulation across all registrations."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if field_id is None:
            return self.render(rs, "field_set_select",
                               {'event_data': event_data})
        else:
            if field_id not in event_data['fields']:
                return werkzeug.exceptions.NotFound("Wrong associated event.")
            return self.redirect(rs, "event/field_set_form",
                                 {'field_id': field_id})

    @access("event")
    @REQUESTdata(("field_id", "id"))
    @event_guard(check_offline=True)
    def field_set_form(self, rs, event_id, field_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if field_id not in event_data['fields']:
            ## also catches field_id validation errors
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        persona_data = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        ordered = sorted(
            registration_data.keys(),
            key=lambda anid: name_key(
                persona_data[registration_data[anid]['persona_id']]))
        field_name = event_data['fields'][field_id]['field_name']
        values = {
            "input{}".format(registration_id):
            rdata['field_data'].get(field_name)
            for registration_id, rdata in registration_data.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "field_set", {
            'event_data': event_data, 'registration_data': registration_data,
            'persona_data': persona_data, 'ordered': ordered})

    @access("event", modi={"POST"})
    @REQUESTdata(("field_id", "id"))
    @event_guard(check_offline=True)
    def field_set(self, rs, event_id, field_id):
        """Modify a specific field on all registrations."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if field_id not in event_data['fields']:
            ## also catches field_id validation errors
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registrations = self.eventproxy.list_registrations(rs, event_id)
        kind = "{}_or_None".format(event_data['fields'][field_id]['kind'])
        data_params = tuple(("input{}".format(registration_id), kind)
                            for registration_id in registrations)
        data = request_data_extractor(rs, data_params)
        if rs.errors:
            return self.field_set_form(rs, event_id, field_id)

        registration_data = self.eventproxy.get_registrations(rs, registrations)
        code = 1
        field_name = event_data['fields'][field_id]['field_name']
        for registration_id, rdata in registration_data.items():
            if (data["input{}".format(registration_id)]
                    != rdata['field_data'].get(field_name)):
                new_data = {
                    'id': registration_id,
                    'field_data': {
                        field_name: data["input{}".format(registration_id)]
                    }
                }
                code *= self.eventproxy.set_registration(rs, new_data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs, event_id):
        """Lock an event for offline usage."""
        code = self.eventproxy.lock_event(rs, event_id)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @REQUESTfile("json_data")
    def unlock_event(self, rs, event_id, json_data):
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        data = check(rs, "serialized_event_upload", json_data)
        if rs.errors:
            return self.show_event(rs, event_id)
        if event_id != data['id']:
            rs.notify("error", "Data from wrong event.")
            return self.show_event(rs, event_id)
        ## Check for unmigrated personas
        current = self.eventproxy.export_event(rs, event_id)
        claimed = {e['persona_id'] for e in data['event.registrations']
                   if not e['real_persona_id']}
        if claimed - {e['id'] for e in current['core.personas']}:
            rs.notify("error", "There exist unmigrated personas.")
            return self.show_event(rs, event_id)

        code = self.eventproxy.unlock_import_event(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "event/show_event")

    @access("event_admin", modi={"POST"})
    @event_guard(check_offline=True)
    def archive_event(self, rs, event_id):
        """Make a past_event from an event.

        This is at the boundary between event and cde frontend, since
        the past-event stuff generally resides in the cde realm.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if event_data['is_archived']:
            rs.notify("warning", "Event already archived.")
            return self.redirect(rs, "event/show_event")
        new_id, message = self.pasteventproxy.archive_event(rs, event_id)
        if not new_id:
            rs.notify("warning", message)
            return self.redirect(rs, "event/show_event")
        rs.notify("success", "Event archived.")
        return self.redirect(rs, "cde/show_past_event", {'pevent_id': new_id})

    @access("event_admin")
    @REQUESTdata(("codes", "[int]"), ("event_id", "id_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_log(self, rs, codes, event_id, start, stop):
        """View activities concerning events organized via DB."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.eventproxy.retrieve_log(rs, codes, event_id, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        events = {entry['event_id'] for entry in log if entry['event_id']}
        event_data = self.eventproxy.get_event_data(rs, events)
        events = self.eventproxy.list_db_events(rs)
        return self.render(rs, "view_log", {
            'log': log, 'persona_data': persona_data, 'event_data': event_data,
            'events': events})

    @access("event")
    @event_guard()
    @REQUESTdata(("codes", "[int]"), ("start", "int_or_None"),
                 ("stop", "int_or_None"))
    def view_event_log(self, rs, event_id, codes, start, stop):
        """View activities concerning one event organized via DB."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.eventproxy.retrieve_log(rs, codes, event_id, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        return self.render(rs, "view_event_log", {
            'log': log, 'persona_data': persona_data, 'event_data': event_data})
