#!/usr/bin/env python3

"""Services for the event realm."""

from collections import OrderedDict
import copy
import itertools
import os
import os.path
import re
import shutil
import tempfile

import werkzeug

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, registration_is_open,
    check_validation as check, event_guard,
    REQUESTfile, request_extractor, cdedbid_filter)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input, Query
from cdedb.common import (
    name_key, merge_dicts, determine_age_class, deduct_years, AgeClasses,
    unwrap, now, ProxyShim, json_serialize)
from cdedb.backend.event import EventBackend
from cdedb.backend.past_event import PastEventBackend
import cdedb.database.constants as const

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

    def finalize_session(self, rs, auxilliary=False):
        super().finalize_session(rs, auxilliary=auxilliary)
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
    def event_begin(event):
        """Small helper to calculate the begin of an event.

        :type event: {str: object}
        :param event: event dataset as returned by the backend
        :rtype: datetime.date
        """
        return min((p['part_begin'] for p in event['parts'].values()),
                   default=now().date())

    @staticmethod
    def event_end(event):
        """Small helper to calculate the end of an event.

        :type event: {str: object}
        :param event: event dataset as returned by the backend
        :rtype: datetime.date
        """
        return max((p['part_end'] for p in event['parts'].values()),
                   default=now().date())

    def is_locked(self, event):
        """Shorthand to deremine locking state of an event.

        :type event: {str: object}
        :rtype: bool
        """
        return event['offline_lock'] != self.conf.CDEDB_OFFLINE_DEPLOYMENT

    @staticmethod
    def event_has_field(event, field_name):
        """Shorthand to check whether a field with given name is defined for
        an event.

        :type event: {str: object}
        :type field_name: str
        :rtype: bool
        """
        return any(field['field_name'] == field_name
                   for field in event['fields'].values())

    @access("persona")
    def index(self, rs):
        """Render start page."""
        open_event_list = self.eventproxy.list_open_events(rs)
        open_events = self.eventproxy.get_events(rs, open_event_list.keys())
        orga_events = self.eventproxy.get_events(rs, rs.user.orga)
        for event in itertools.chain(open_events.values(),
                                     orga_events.values()):
            event['begin'] = self.event_begin(event)
            event['end'] = self.event_end(event)
        return self.render(rs, "index", {
            'open_events': open_events, 'orga_events': orga_events,})

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
        spec = copy.deepcopy(QUERY_SPECS['qview_event_user'])
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
                data = self.fill_template(rs, 'web', 'csv_search_result',
                                          params)
                return self.send_file(rs, data=data, inline=False,
                                      filename=self.i18n("result.txt", rs.lang))
        else:
            rs.values['is_search'] = is_search = False
        return self.render(rs, "user_search", params)

    @access("event_admin")
    def list_db_events(self, rs):
        """List all events organized via DB."""
        events = self.eventproxy.list_db_events(rs)
        events = self.eventproxy.get_events(rs, events.keys())
        for event in events.values():
            event['begin'] = self.event_begin(event)
            event['end'] = self.event_end(event)
        return self.render(rs, "list_db_events", {'events': events})

    @access("event")
    def show_event(self, rs, event_id):
        """Display event organized via DB."""
        rs.ambience['event']['is_open'] = registration_is_open(
            rs.ambience['event'])
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
        rs.ambience['event']['is_open'] = registration_is_open(
            rs.ambience['event'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        if course_ids:
            courses = self.eventproxy.get_courses(rs, course_ids.keys())
        else:
            courses = None
        return self.render(rs, "course_list", {'courses': courses,})

    @access("event")
    @event_guard(check_offline=True)
    def change_event_form(self, rs, event_id):
        """Render form."""
        institutions = self.pasteventproxy.list_institutions(rs)
        merge_dicts(rs.values, rs.ambience['event'])
        return self.render(rs, "change_event", {'institutions': institutions})

    @access("event", modi={"POST"})
    @REQUESTdatadict(
        "title", "institution", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "use_questionnaire", "notes")
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

        This can drop your own orga role.
        """
        if rs.errors:
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
        courses = self.eventproxy.get_courses(rs, course_ids)
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
        delete_flags = request_extractor(
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
        data = request_extractor(rs, params)
        ret = {
            part_id: {key: data["{}_{}".format(key, part_id)] for key in spec}
            for part_id in parts if part_id not in deletes
        }
        for part_id in deletes:
            ret[part_id] = None
        marker = 1
        while marker < 2**10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                params = tuple(("{}_-{}".format(key, marker), value)
                               for key, value in spec.items())
                data = request_extractor(rs, params)
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
                               ("entries_{}".format(anid), "str_or_None"))
        for field_id in fields:
            if field_id not in deletes:
                tmp = request_extractor(rs, params(field_id))
                temp = {}
                temp['kind'] = tmp["kind_{}".format(field_id)]
                temp['entries'] = tmp["entries_{}".format(field_id)]
                temp = check(rs, "event_field", temp)
                if temp:
                    ret[field_id] = temp
        for field_id in deletes:
            ret[field_id] = None
        marker = 1
        params = lambda anid: (("field_name_-{}".format(anid), "str"),
                               ("kind_-{}".format(anid), "str"),
                               ("entries_-{}".format(anid), "str_or_None"))
        while marker < 2**10:
            will_create = unwrap(request_extractor(
                rs, (("create_-{}".format(marker), "bool"),)))
            if will_create:
                tmp = request_extractor(rs, params(marker))
                temp = {}
                temp['field_name'] = tmp["field_name_-{}".format(marker)]
                temp['kind'] = tmp["kind_-{}".format(marker)]
                temp['entries'] = tmp["entries_-{}".format(marker)]
                temp = check(rs, "event_field", temp, creation=True)
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
        code = self.eventproxy.set_event(rs, event)
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
        data = check(rs, "event", data, creation=True)
        if rs.errors:
            return self.create_event_form(rs)
        new_id = self.eventproxy.create_event(rs, data)
        # TODO create mailing lists
        self.notify_return_code(rs, new_id, success="Event created.")
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event")
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        params = {}
        if event_id in rs.user.orga or self.is_admin(rs):
            registration_ids = self.eventproxy.list_registrations(rs, event_id)
            registrations = {
                k: v for k, v in self.eventproxy.get_registrations(
                    rs, registration_ids).items()
                if any(part['course_id'] == course_id
                       or part['course_instructor'] == course_id
                       for part in v['parts'].values())}
            personas = self.coreproxy.get_personas(
                rs, tuple(e['persona_id'] for e in registrations.values()))
            attendees = self.calculate_groups(
                (course_id,), rs.ambience['event'], registrations,
                key="course_id", personas=personas)
            params['personas'] = personas
            params['registrations'] = registrations
            params['attendees'] = attendees
        return self.render(rs, "show_course", params)

    @access("event")
    @event_guard(check_offline=True)
    def change_course_form(self, rs, event_id, course_id):
        """Render form."""
        if 'parts' not in rs.values:
            rs.values.setlist('parts', rs.ambience['course']['parts'])
        if 'active_parts' not in rs.values:
            rs.values.setlist('active_parts',
                              rs.ambience['course']['active_parts'])
        merge_dicts(rs.values, rs.ambience['course'])
        return self.render(rs, "change_course")

    @access("event", modi={"POST"})
    @REQUESTdata(("parts", "[int]"), ("active_parts", "[int]"), )
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "max_size", "min_size", "notes")
    @event_guard(check_offline=True)
    def change_course(self, rs, event_id, course_id, parts, active_parts, data):
        """Modify a course associated to an event organized via DB."""
        data['id'] = course_id
        data['parts'] = parts
        data['active_parts'] = active_parts
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
        ## by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', rs.ambience['event']['parts'])
        return self.render(rs, "create_course")

    @access("event", modi={"POST"})
    @REQUESTdata(("parts", "[int]"))
    @REQUESTdatadict("title", "description", "nr", "shortname", "instructors",
                     "max_size", "min_size", "notes")
    @event_guard(check_offline=True)
    def create_course(self, rs, event_id, parts, data):
        """Create a new course associated to an event organized via DB."""
        data['event_id'] = event_id
        data['parts'] = parts
        data = check(rs, "course", data, creation=True)
        if rs.errors:
            return self.create_course_form(rs, event_id)
        new_id = self.eventproxy.create_course(rs, data)
        self.notify_return_code(rs, new_id, success="Course created.")
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event")
    @event_guard()
    def stats(self, rs, event_id):
        """Present an overview of the basic stats."""
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        courses = self.eventproxy.list_db_courses(rs, event_id)
        personas = self.coreproxy.get_event_users(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        stati = const.RegistrationPartStati
        get_age = lambda u: determine_age_class(
            u['birthday'], self.event_begin(rs.ambience['event']))
        tests = OrderedDict((
            ('total', (lambda e, r, p: (
                p['status'] != stati.not_applied))),
            ('pending', (lambda e, r, p: (
                p['status'] == stati.applied))),
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
            (' instructors', (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and p['course_id'] == p['course_instructor']))),
            (' attendees', (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and p['course_id'] != p['course_instructor']))),
            (' first choice', (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and len(r['choices'][p['part_id']]) > 0
                and (r['choices'][p['part_id']][0]
                     == p['course_id'])))),
            (' second choice', (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and len(r['choices'][p['part_id']]) > 1
                and (r['choices'][p['part_id']][1]
                     == p['course_id'])))),
            (' third choice', (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and len(r['choices'][p['part_id']]) > 2
                and (r['choices'][p['part_id']][2]
                     == p['course_id'])))),
            ('waitlist', (lambda e, r, p: (
                p['status'] == stati.waitlist))),
            ('guest', (lambda e, r, p: (
                p['status'] == stati.guest))),
            ('cancelled', (lambda e, r, p: (
                p['status'] == stati.cancelled))),
            ('rejected', (lambda e, r, p: (
                p['status'] == stati.rejected))),))
        if not courses:
            for key in (' instructors', ' attendees', ' first choice',
                        ' second choice', ' third choice'):
                del tests[key]
        statistics = OrderedDict()
        for key, test in tests.items():
            statistics[key] = {
                part_id: sum(
                    1 for r in registrations.values()
                    if test(rs.ambience['event'], r, r['parts'][part_id]))
                for part_id in rs.ambience['event']['parts']}
        tests2 = {
            'not payed': (lambda e, r, p: (
                stati(p['status']).is_involved()
                and not r['payment'])),
            'pending': (lambda e, r, p: (
                p['status'] == stati.applied
                and r['payment'])),
            'no parental agreement': (lambda e, r, p: (
                stati(p['status']).is_involved()
                and get_age(personas[r['persona_id']]).is_minor()
                and not r['parental_agreement'])),
            'no lodgement': (lambda e, r, p: (
                stati(p['status']).is_present()
                and not p['lodgement_id'])),
            'no course': (lambda e, r, p: (
                p['status'] == stati.participant
                and not p['course_id']
                and r['persona_id'] not in e['orgas'])),
            'wrong choice': (lambda e, r, p: (
                p['status'] == stati.participant
                and p['course_id']
                and (p['course_id']
                     not in r['choices'][p['part_id']]))),
        }
        sorter = lambda registration_id: name_key(
            personas[registrations[registration_id]['persona_id']])
        listings = {
            key: {
                part_id: sorted(
                    (registration_id
                     for registration_id, r in registrations.items()
                     if test(rs.ambience['event'], r, r['parts'][part_id])),
                    key=sorter)
                for part_id in rs.ambience['event']['parts']
            }
            for key, test in tests2.items()
        }
        return self.render(rs, "stats", {
            'registrations': registrations, 'personas': personas,
            'courses': courses, 'statistics': statistics, 'listings': listings})

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
        courses = self.eventproxy.get_courses(rs, course_ids)

        all_reg_ids = self.eventproxy.list_registrations(rs, event_id)
        all_regs = self.eventproxy.get_registrations(rs, all_reg_ids)
        course_infos = {}
        stati = const.RegistrationPartStati
        for course_id, course in courses.items():
            for part_id in rs.ambience['event']['parts']:
                assigned = sum(
                    1 for reg in all_regs.values()
                    if reg['parts'][part_id]['status'] == stati.participant
                    and reg['parts'][part_id]['course_id'] == course_id)
                all_instructors = sum(
                    1 for reg in all_regs.values()
                    if reg['parts'][part_id]['course_instructor'] == course_id)
                assigned_instructors = sum(
                    1 for reg in all_regs.values()
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

        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        courses = None
        if action == -2:
            course_ids = self.eventproxy.list_db_courses(rs, event_id)
            courses = self.eventproxy.get_courses(rs, course_ids)
        elif action in {-1, 0, 1, 2}:
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
                reg_part = registrations[registration_id]['parts'][part_id]
                choices = registrations[registration_id]['choices']
                if (reg_part['status']
                        != const.RegistrationPartStati.participant):
                    continue
                if action >= 0:
                    try:
                        choice = choices[part_id][action]
                    except IndexError:
                        rs.notify("error", "No choice available.")
                    else:
                        tmp['parts'][part_id] = {'course_id': choice}
                elif action == -1:
                    tmp['parts'][part_id] = {'course_id': course_id}
                elif action == -2:
                    ## Automatic assignment
                    cid = reg_part['course_id']
                    if cid and part_id in courses[cid]['active_parts']:
                        ## Do not modify a valid assignment
                        continue
                    instructor = reg_part['course_instructor']
                    if (instructor
                            and part_id in courses[instructor]['active_parts']):
                        ## Let instructors instruct
                        tmp['parts'][part_id] = {'course_id': instructor}
                        continue
                    for choice in choices[part_id]:
                        if part_id in courses[choice]['active_parts']:
                            ## Assign first possible choice
                            tmp['parts'][part_id] = {'course_id': choice}
                            break
                    else:
                        rs.notify("error", "No choice available.")
            if tmp['parts']:
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
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        choice_counts = {
            course_id: {
                (part_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['choices'][part_id]) > i
                        and reg['choices'][part_id][i] == course_id
                        and (reg['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for part_id in event['parts']
                for i in range(3)
            }
            for course_id in course_ids
        }
        assign_counts = {
            course_id: {
                part_id: sum(
                    1 for reg in registrations.values()
                    if (reg['parts'][part_id]['course_id'] == course_id
                        and (reg['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for part_id in event['parts']
            }
            for course_id in course_ids
        }
        return self.render(rs, "course_stats", {
            'courses': courses, 'choice_counts': choice_counts,
            'assign_counts': assign_counts})

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
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                self.event_begin(rs.ambience['event']))
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        tex = self.fill_template(rs, "tex", "nametags", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'courses': courses})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = os.path.join(tmp_dir, rs.ambience['event']['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "nametags.tex"), 'w') as f:
                f.write(tex)
            src = os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png")
            shutil.copy(src, os.path.join(work_dir, "aka-logo.png"))
            shutil.copy(src, os.path.join(work_dir, "orga-logo.png"))
            shutil.copy(src, os.path.join(work_dir, "minor-pictogram.png"))
            for course_id in courses:
                shutil.copy(src, os.path.join(
                    work_dir, "logo-{}.png".format(course_id)))
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'], "nametags.tex",
                runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_puzzle(self, rs, event_id, runs):
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        event = rs.ambience['event']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        counts = {
            course_id: {
                (part_id, i): sum(
                    1 for reg in registrations.values()
                    if (len(reg['choices'][part_id]) > i
                        and reg['choices'][part_id][i] == course_id
                        and (reg['parts'][part_id]['status']
                             == const.RegistrationPartStati.participant)
                        and reg['persona_id'] not in event['orgas']))
                for part_id in event['parts']
                for i in range(3)
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
        participants. This make use of the fields 'lodge' and 'may_reserve'.
        """
        event = rs.ambience['event']
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                self.event_begin(event))
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        lodge_present = any(field['field_name'] == "lodge"
                            for field in event['fields'].values())
        may_reserve_present = any(field['field_name'] == "may_reserve"
                                  for field in event['fields'].values())
        tex = self.fill_template(rs, "tex", "lodgement_puzzle", {
            'lodgements': lodgements, 'registrations': registrations,
            'personas': personas, 'lodge_present': lodge_present,
            'may_reserve_present': may_reserve_present})
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
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        attendees = self.calculate_groups(
            courses, rs.ambience['event'], registrations, key="course_id",
            personas=personas)
        tex = self.fill_template(rs, "tex", "course_lists", {
            'courses': courses, 'registrations': registrations,
            'personas': personas, 'attendees': attendees})
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = os.path.join(tmp_dir, rs.ambience['event']['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "course_lists.tex"), 'w') as f:
                f.write(tex)
            for course_id in courses:
                shutil.copy(
                    os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png"),
                    os.path.join(work_dir, "logo-{}.png".format(course_id)))
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "course_lists.tex", runs)

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
            work_dir = os.path.join(tmp_dir, rs.ambience['event']['shortname'])
            os.mkdir(work_dir)
            with open(os.path.join(work_dir, "lodgement_lists.tex"), 'w') as f:
                f.write(tex)
            shutil.copy(
                os.path.join(self.conf.REPOSITORY_PATH, "misc/logo.png"),
                os.path.join(work_dir, "aka-logo.png"))
            return self.serve_complex_latex_document(
                rs, tmp_dir, rs.ambience['event']['shortname'],
                "lodgement_lists.tex", runs)

    @access("event")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_participant_list(self, rs, event_id, runs):
        """Create list to send to all participants."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v
            for k, v in self.eventproxy.get_registrations(
                rs, registration_ids).items()
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
            'personas': personas, 'ordered': ordered})
        return self.serve_latex_document(rs, tex, "participant_list", runs)

    @access("event")
    @event_guard()
    def download_expuls(self, rs, event_id):
        """Create TeX-snippet for announcement in the ExPuls."""
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids)
        tex = self.fill_template(rs, "tex", "expuls", {'courses': courses})
        return self.send_file(rs, data=tex, inline=False,
                              filename=self.i18n("expuls.tex", rs.lang))

    @access("event")
    @event_guard()
    def download_export(self, rs, event_id):
        """Retrieve all data for this event to initialize an offline
        instance."""
        data = self.eventproxy.export_event(rs, event_id)
        json = json_serialize(data)
        return self.send_file(rs, data=json, inline=False,
                              filename=self.i18n("export_event.json", rs.lang))

    @access("event")
    def register_form(self, rs, event_id):
        """Render form."""
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if rs.user.persona_id in registrations.values():
            rs.notify("info", "Allready registered.")
            return self.redirect(rs, "event/registration_status")
        if not registration_is_open(rs.ambience['event']):
            rs.notify("warning", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/show_event")
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'],
            self.event_begin(rs.ambience['event']))
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        if not minor_form_present and age.is_minor():
            rs.notify("info", "No minors may register.")
            return self.redirect(rs, "event/show_event")
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in courses
                            if part_id in courses[course_id]['parts'])
            for part_id in rs.ambience['event']['parts']}
        ## by default select all parts
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
        standard_params = (("mixed_lodging", "bool"), ("foto_consent", "bool"),
                           ("notes", "str_or_None"))
        if parts is None:
            standard_params += (("parts", "[int]"),)
        standard = request_extractor(rs, standard_params)
        if parts is not None:
            standard['parts'] = tuple(
                part_id for part_id, entry in parts.items()
                if const.RegistrationPartStati(entry['status']).is_involved())
        choice_params = (("course_choice{}_{}".format(part_id, i), "id")
                         for part_id in standard['parts']
                         for i in range(3))
        choices = request_extractor(rs, choice_params)
        instructor_params = (
            ("course_instructor{}".format(part_id), "id_or_None")
            for part_id in standard['parts'])
        instructor = request_extractor(rs, instructor_params)
        if not standard['parts']:
            rs.errors.append(("parts",
                              ValueError("Must select at least one part.")))
        parts_with_courses = set()
        for part_id in standard['parts']:
            ## only check for course choices if there are courses to choose
            if any(part_id in c['parts'] for c in courses.values()):
                parts_with_courses.add(part_id)
                cids = {choices["course_choice{}_{}".format(part_id, i)]
                        for i in range(3)}
                if len(cids) != 3:
                    rs.errors.extend(
                        ("course_choice{}_{}".format(part_id, i),
                         ValueError("Must choose three different courses."))
                        for i in range(3))
        if not standard['foto_consent']:
            rs.errors.append(("foto_consent", ValueError("Must consent.")))
        reg_parts = {
            part_id: {
                'course_instructor':
                    instructor.get("course_instructor{}".format(part_id)),
            }
            for part_id in event['parts']
        }
        if parts is None:
            for part_id in reg_parts:
                stati = const.RegistrationPartStati
                if part_id in standard['parts']:
                    reg_parts[part_id]['status'] = stati.applied
                else:
                    reg_parts[part_id]['status'] = stati.not_applied
        choices = {
            part_id: tuple(choices["course_choice{}_{}".format(part_id, i)]
                           for i in range(3))
            for part_id in parts_with_courses
        }
        registration = {
            'mixed_lodging': standard['mixed_lodging'],
            'foto_consent': standard['foto_consent'],
            'notes': standard['notes'],
            'parts': reg_parts,
            'choices': choices,
        }
        return registration

    @access("event", modi={"POST"})
    def register(self, rs, event_id):
        """Register for an event."""
        if not registration_is_open(rs.ambience['event']):
            rs.notify("error", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", "Event locked.")
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
            persona['birthday'], self.event_begin(rs.ambience['event']))
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        if not minor_form_present and age.is_minor():
            rs.notify("error", "No minors may register.")
            return self.redirect(rs, "event/show_event")
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        new_id = self.eventproxy.create_registration(rs, registration)
        fee = sum(rs.ambience['event']['parts'][part_id]['fee']
                  for part_id, entry in registration['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved())
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': 'Registered for event {}'.format(
                 rs.ambience['event']['title'])},
            {'fee': fee, 'age': age})
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
        registration = self.eventproxy.get_registration(rs, registration_id)
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], self.event_begin(rs.ambience['event']))
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
        registration_id = unwrap(self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id), keys=True)
        if not registration_id:
            rs.notify("warning", "Not registered for event.")
            return self.redirect(rs, "event/show_event")
        registration = self.eventproxy.get_registration(rs, registration_id)
        if (rs.ambience['event']['registration_soft_limit'] and
                now().date() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("warning", "Registration closed, no changes possible.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        persona = self.coreproxy.get_event_user(rs, rs.user.persona_id)
        age = determine_age_class(
            persona['birthday'], self.event_begin(rs.ambience['event']))
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in courses
                            if part_id in courses[course_id]['parts'])
            for part_id in rs.ambience['event']['parts']}
        non_trivials = {}
        for part_id in registration['parts']:
            for i, choice in enumerate(
                    registration['choices'].get(part_id, [])):
                param = "course_choice{}_{}".format(part_id, i)
                non_trivials[param] = choice
        for part_id, entry in registration['parts'].items():
            param = "course_instructor{}".format(part_id)
            non_trivials[param] = entry['course_instructor']
        merge_dicts(rs.values, non_trivials, registration)
        return self.render(rs, "amend_registration", {
            'age': age, 'courses': courses, 'course_choices': course_choices,
            'parts': registration['parts'],})

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
        if (rs.ambience['event']['registration_soft_limit'] and
                now().date() > rs.ambience['event']['registration_soft_limit']):
            rs.notify("error", "No changes allowed anymore.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", "Event locked.")
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
            persona['birthday'], self.event_begin(rs.ambience['event']))
        registration['mixed_lodging'] = (registration['mixed_lodging']
                                         and age.may_mix())
        code = self.eventproxy.set_registration(rs, registration)
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
        registration = self.eventproxy.get_registration(rs, registration_id)
        if not rs.ambience['event']['use_questionnaire']:
            rs.notify("warning", "Questionnaire disabled.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("info", "Event locked.")
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        merge_dicts(rs.values, registration['fields'])
        return self.render(rs, "questionnaire", {
            'questionnaire': questionnaire,})

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
        if not rs.ambience['event']['use_questionnaire']:
            rs.notify("error", "Questionnaire disabled.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(rs.ambience['event']):
            rs.notify("error", "Event locked.")
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
            'id': registration_id, 'fields': data,})
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
        while marker < 2**10:
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
            persona['birthday'], self.event_begin(rs.ambience['event']))
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        return self.render(rs, "show_registration", {
            'persona': persona, 'age': age, 'courses': courses,
            'lodgements': lodgements,})

    @access("event")
    @event_guard(check_offline=True)
    def change_registration_form(self, rs, event_id, registration_id):
        """Render form."""
        registration = rs.ambience['registration']
        persona = self.coreproxy.get_persona(rs, registration['persona_id'])
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in courses
                            if part_id in courses[course_id]['parts'])
            for part_id in rs.ambience['event']['parts']}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        reg_values = {"reg.{}".format(key): value
                      for key, value in registration.items()}
        part_values = []
        for part_id in registration['parts']:
            one_part = {
                "part{}.{}".format(part_id, key): value
                for key, value in registration['parts'][part_id].items()}
            for i, course_choice in enumerate(
                    registration['choices'].get(part_id, [])):
                key = 'part{}.course_choice_{}'.format(part_id, i)
                one_part[key] = course_choice
            part_values.append(one_part)
        field_values = {
            "fields.{}".format(key): value
            for key, value in registration['fields'].items()}
        ## Fix formatting of ID
        reg_values['reg.real_persona_id'] = cdedbid_filter(
            reg_values['reg.real_persona_id'])
        merge_dicts(rs.values, reg_values, field_values, *part_values)
        return self.render(rs, "change_registration", {
            'persona': persona, 'courses': courses,
            'course_choices': course_choices, 'lodgements': lodgements})

    @staticmethod
    def process_orga_registration_input(rs, event, do_fields=True):
        """Helper to handle input by orgas.

        This takes care of extracting the values and validating them. Which
        values to extract depends on the event. This puts less restrictions
        on the input (like not requiring three different course choices).

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type do_fields: bool
        :rtype: {str: object}
        :returns: registration data set
        """
        reg_params = (
            ("reg.notes", "str_or_None"), ("reg.orga_notes", "str_or_None"),
            ("reg.payment", "date_or_None"), ("reg.parental_agreement", "bool"),
            ("reg.mixed_lodging", "bool"), ("reg.checkin", "date_or_None"),
            ("reg.foto_consent", "bool"),
            ("reg.real_persona_id", "cdedbid_or_None"))
        raw_reg = request_extractor(rs, reg_params)
        part_params = []
        for part_id in event['parts']:
            prefix = "part{}".format(part_id)
            part_params.append(("{}.status".format(prefix),
                                "enum_registrationpartstati"))
            part_params.extend(
                ("{}.{}".format(prefix, suffix), "id_or_None")
                for suffix in ("course_id", "course_choice_0",
                               "course_choice_1", "course_choice_2",
                               "course_instructor", "lodgement_id"))
        raw_parts = request_extractor(rs, part_params)
        field_params = tuple(
            ("fields.{}".format(field['field_name']),
             "{}_or_None".format(field['kind']))
            for field in event['fields'].values())
        raw_fields = request_extractor(rs, field_params)

        new_parts = {
            part_id: {
                key: raw_parts["part{}.{}".format(part_id, key)]
                for key in ("status", "course_id", "course_instructor",
                            "lodgement_id")
            }
            for part_id in event['parts']
        }
        new_choices = {}
        for part_id in event['parts']:
            extractor = lambda i: raw_parts["part{}.course_choice_{}".format(
                part_id, i)]
            new_choices[part_id] = tuple(extractor(i)
                                         for i in range(3) if extractor(i))
        new_fields = {
            key.split('.', 1)[1]: value for key, value in raw_fields.items()}

        registration = {
            key.split('.', 1)[1]: value for key, value in raw_reg.items()}
        registration['parts'] = new_parts
        registration['choices'] = new_choices
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
            rs, rs.ambience['event'])
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
        course_ids = self.eventproxy.list_db_courses(rs, event_id)
        courses = self.eventproxy.get_courses(rs, course_ids.keys())
        course_choices = {
            part_id: sorted(course_id for course_id in courses
                            if part_id in courses[course_id]['parts'])
            for part_id in rs.ambience['event']['parts']}
        lodgement_ids = self.eventproxy.list_lodgements(rs, event_id)
        lodgements = self.eventproxy.get_lodgements(rs, lodgement_ids)
        return self.render(rs, "add_registration", {
            'courses': courses, 'course_choices': course_choices,
            'lodgements': lodgements,})

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
                              ValueError("Invalid persona.")))
        if not rs.errors and self.eventproxy.list_registrations(
                rs, event_id, persona_id=persona_id):
            rs.errors.append(("persona.persona_id",
                              ValueError("Allready registered.")))
        registration = self.process_orga_registration_input(
            rs, rs.ambience['event'], do_fields=False)
        if rs.errors:
            return self.add_registration_form(rs, event_id)

        registration['persona_id'] = persona_id
        registration['event_id'] = event_id
        new_id = self.eventproxy.create_registration(rs, registration)
        self.notify_return_code(rs, new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

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
        def _check_belonging(entity_id, part_id, registration_id):
            """The actual check, un-inlined."""
            part = registrations[registration_id]['parts'][part_id]
            return (
                part[key] == entity_id
                and const.RegistrationPartStati(part['status']).is_present())
        if personas is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: name_key(
                personas[registrations[anid]['persona_id']])
        return {
            (entity_id, part_id): sorted(
                (registration_id for registration_id in registrations
                 if _check_belonging(entity_id, part_id, registration_id)),
                key=sorter)
            for entity_id in entity_ids
            for part_id in event['parts']
        }

    @classmethod
    def check_lodgment_problems(cls, event, lodgements,
                                registrations, personas, inhabitants):
        """Un-inlined code to examine the current lodgements of an event for
        spots with room for improvement.

        This makes use of the 'reserve' field.

        :type event: {str: object}
        :type lodgements: {int: {str: object}}
        :type registrations: {int: {str: object}}
        :type personas: {int: {str: object}}
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
                personas[registrations[a]['persona_id']]['gender']
                != personas[registrations[b]['persona_id']]['gender']
                for a, b in itertools.combinations(group, 2))
        def _mixing_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for mixing problems."""
            return (
                "Mixed lodgement with non-mixing participants.",
                lodgement_id, part_id, tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if not registrations[reg_id]['mixed_lodging']))
        def _reserve(group, part_id):
            """Un-inlined code to count the number of registrations assigned
            to a lodgement as reserve lodgers."""
            return sum(
                1 for reg_id in group
                if registrations[reg_id]['fields'].get(
                    'reserve_{}'.format(part_id)))
        def _reserve_problem(lodgement_id, part_id):
            """Un-inlined code to generate an entry for reserve problems."""
            return (
                "Wrong number of reserve lodgers used.", lodgement_id, part_id,
                tuple(
                    reg_id for reg_id in inhabitants[(lodgement_id, part_id)]
                    if registrations[reg_id]['fields'].get(
                        'reserve_{}'.format(part_id))))

        ## now the actual work
        for lodgement_id in lodgements:
            for part_id in event['parts']:
                group = inhabitants[(lodgement_id, part_id)]
                lodgement = lodgements[lodgement_id]
                if len(group) > lodgement['capacity'] + lodgement['reserve']:
                    ret.append(("Overful lodgement.", lodgement_id, part_id,
                                tuple()))
                if _mixed(group) and any(
                        not registrations[reg_id]['mixed_lodging']
                        for reg_id in group):
                    ret.append(_mixing_problem(lodgement_id, part_id))
                if (cls.event_has_field(event, 'reserve')
                        and (len(group) - lodgement['capacity']
                             != _reserve(group, part_id))
                        and ((len(group) - lodgement['capacity'] > 0)
                             or _reserve(group, part_id))):
                    ret.append(_reserve_problem(lodgement_id, part_id))
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

        problems = self.check_lodgment_problems(
            rs.ambience['event'], lodgements, registrations, personas,
            inhabitants)

        return self.render(rs, "lodgements", {
            'lodgements': lodgements,
            'registrations': registrations, 'personas': personas,
            'inhabitants': inhabitants, 'problems': problems,})

    @access("event")
    @event_guard()
    def show_lodgement(self, rs, event_id, lodgement_id):
        """Display details of one lodgement."""
        # TODO check whether this is deletable
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v for k, v in self.eventproxy.get_registrations(
                rs, registration_ids).items()
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
            'inhabitants': inhabitants, 'problems': problems,})

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
        merge_dicts(rs.values, rs.ambience['lodgement'])
        return self.render(rs, "change_lodgement")

    @access("event", modi={"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def change_lodgement(self, rs, event_id, lodgement_id, data):
        """Alter the attributes of a lodgement.

        This does not enable changing the inhabitants of this lodgement.
        """
        data['id'] = lodgement_id
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
            rs.notify("error", "Not deleting a non-empty lodgement.")
            return self.redirect(rs, "event/show_lodgement")
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
        def _check_with_lodgement(registration_id, part_id):
            """Un-inlined check for registration with different lodgement."""
            part = registrations[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(part['status']).is_present()
                    and part['lodgement_id']
                    and part['lodgement_id'] != lodgement_id)
        with_lodgement = {
            part_id: sorted(
                (registration_id
                 for registration_id in registrations
                 if _check_with_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
                    personas[registrations[anid]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }
        return self.render(rs, "manage_inhabitants", {
            'registrations': registrations,
            'personas': personas, 'inhabitants': inhabitants,
            'without_lodgement': without_lodgement,
            'with_lodgement': with_lodgement})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs, event_id, lodgement_id):
        """Alter who is assigned to a lodgement.

        This tries to be a bit smart and write only changed state.
        """
        params = tuple(("inhabitants_{}".format(part_id), "int_csv_list")
                       for part_id in rs.ambience['event']['parts'])
        data = request_extractor(rs, params)
        if rs.errors:
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        code = 1
        for registration_id, registration in registrations.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            for part_id in rs.ambience['event']['parts']:
                inhabits = (registration_id
                            in data["inhabitants_{}".format(part_id)])
                if (inhabits
                        != (lodgement_id
                            == registration['parts'][part_id]['lodgement_id'])):
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
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        attendees = self.calculate_groups(
            (course_id,), rs.ambience['event'], registrations, key="course_id",
            personas=personas)
        def _check_without_course(registration_id, part_id):
            """Un-inlined check for registration without course."""
            part = registrations[registration_id]['parts'][part_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and not part['course_id'])
        without_course = {
            part_id: sorted(
                (registration_id
                 for registration_id in registrations
                 if _check_without_course(registration_id, part_id)),
                key=lambda anid: name_key(
                    personas[registrations[anid]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }
        def _check_with_course(registration_id, part_id):
            """Un-inlined check for registration with different course."""
            part = registrations[registration_id]['parts'][part_id]
            return (part['status'] == const.RegistrationPartStati.participant
                    and part['course_id']
                    and part['course_id'] != course_id)
        with_course = {
            part_id: sorted(
                (registration_id
                 for registration_id in registrations
                 if _check_with_course(registration_id, part_id)),
                key=lambda anid: name_key(
                    personas[registrations[anid]['persona_id']])
            )
            for part_id in rs.ambience['event']['parts']
        }
        return self.render(rs, "manage_attendees", {
            'registrations': registrations,
            'personas': personas, 'attendees': attendees,
            'without_course': without_course, 'with_course': with_course})

    @access("event", modi={"POST"})
    @event_guard(check_offline=True)
    def manage_attendees(self, rs, event_id, course_id):
        """Alter who is assigned to this course."""
        params = tuple(("attendees_{}".format(part_id), "int_csv_list")
                       for part_id in rs.ambience['course']['parts'])
        data = request_extractor(rs, params)
        if rs.errors:
            return self.manage_attendees_form(rs, event_id, course_id)
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        code = 1
        for registration_id, registration in registrations.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            for part_id in rs.ambience['course']['parts']:
                attends = (registration_id
                           in data["attendees_{}".format(part_id)])
                part = registration['parts'][part_id]
                if attends != (course_id == part['course_id']):
                    new_reg['parts'][part_id] = {
                        'course_id': (course_id if attends else None)
                    }
            if new_reg['parts']:
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
        spec = copy.deepcopy(QUERY_SPECS['qview_registration'])
        ## note that spec is an ordered dict and we should respect the order
        for part_id in event['parts']:
            spec["part{0}.course_id{0}".format(part_id)] = "id"
            spec["part{0}.status{0}".format(part_id)] = "int"
            spec["part{0}.lodgement_id{0}".format(part_id)] = "id"
            spec["part{0}.course_instructor{0}".format(part_id)] = "id"
        spec[",".join("part{0}.course_id{0}".format(part_id)
                      for part_id in event['parts'])] = "id"
        spec[",".join("part{0}.status{0}".format(part_id)
                      for part_id in event['parts'])] = "int"
        spec[",".join("part{0}.lodgement{0}".format(part_id)
                      for part_id in event['parts'])] = "id"
        spec[",".join("part{0}.course_instructor{0}".format(part_id)
                      for part_id in event['parts'])] = "id"
        for e in sorted(event['fields'].values(),
                        key=lambda e: e['field_name']):
            spec["fields.{}".format(e['field_name'])] = e['kind']
        return spec

    @classmethod
    def make_registracion_query_aux(cls, rs, event, courses,
                                    lodgements):
        """Un-inlined code to prepare input for template.

        :type rs: :py:class:`FrontendRequestState`
        :type event: {str: object}
        :type courses: {int: {str: object}}
        :type lodgements: {int: {str: object}}
        :rtype: ({str: dict}, {str: str})
        :returns: Choices for select inputs and titles for columns.
        """
        choices = {'persona.gender': cls.enum_choice(rs, const.Genders)}
        for part_id in event['parts']:
            choices.update({
                "part{0}.course_id{0}".format(part_id): {
                    course_id: course['title']
                    for course_id, course in courses.items()
                    if part_id in course['parts']},
                "part{0}.status{0}".format(part_id): cls.enum_choice(
                    rs, const.RegistrationPartStati),
                "part{0}.lodgement_id{0}".format(part_id): {
                    lodgement_id: lodgement['moniker']
                    for lodgement_id, lodgement in lodgements.items()},
                "part{0}.course_instructor{0}".format(part_id): {
                    course_id: course['title']
                    for course_id, course in courses.items()
                    if part_id in course['parts']},})
        choices.update({
            "fields.{}".format(field['field_name']): {
                value: desc for value, desc in field['entries']}
            for field in event['fields'].values() if field['entries']})

        titles = {
            "fields.{}".format(field['field_name']): field['field_name']
            for field in event['fields'].values()}
        for part_id, part in event['parts'].items():
            titles.update({
                "part{0}.course_id{0}".format(part_id): cls.i18n(
                    "course (part {})".format(part['title']), rs.lang),
                "part{0}.status{0}".format(part_id): cls.i18n(
                    "registration status (part {})".format(part['title']),
                    rs.lang),
                "part{0}.lodgement_id{0}".format(part_id): cls.i18n(
                    "lodgement (part {})".format(part['title']), rs.lang),
                "part{0}.course_instructor{0}".format(part_id): cls.i18n(
                    "course instructor (part {})".format(part['title']),
                    rs.lang),
            })
        titles.update({
            ",".join("part{0}.course_id{0}".format(part_id)
                     for part_id in event['parts']): cls.i18n(
                         "course (any part)", rs.lang),
            ",".join("part{0}.status{0}".format(part_id)
                     for part_id in event['parts']): cls.i18n(
                         "registration status (any part)", rs.lang),
            ",".join("part{0}.lodgement{0}".format(part_id)
                     for part_id in event['parts']): cls.i18n(
                         "lodgement (any part)", rs.lang),
            ",".join("part{0}.course_instructor{0}".format(part_id)
                     for part_id in event['parts']): cls.i18n(
                         "course instuctor (any part)", rs.lang)})

        return choices, titles

    @access("event")
    @REQUESTdata(("CSV", "bool"), ("is_search", "bool"))
    @event_guard()
    def registration_query(self, rs, event_id, CSV, is_search):
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        spec = self.make_registration_query_spec(rs.ambience['event'])
        ## mangle the input, so we can prefill the form
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
        choices, titles = self.make_registracion_query_aux(
            rs, rs.ambience['event'], courses, lodgements)
        default_queries = self.conf.DEFAULT_QUERIES['qview_registration']
        default_queries["all"] = Query(
            "qview_registration", spec,
            ("reg.id", "persona.given_names", "persona.family_name"),
            tuple(),
            (("reg.id", True),),)
        default_queries["minors"] = Query(
            "qview_registration", spec,
            ("reg.id", "persona.given_names", "persona.family_name",
             "birthday"),
            (("birthday", QueryOperators.greater,
              deduct_years(now().date(), 18)),),
            (("persona.birthday", True), ("reg.id", True)),)
        params = {
            'spec': spec, 'choices': choices, 'query': query,
            'default_queries': default_queries, 'titles': titles,}
        ## Tricky logic: In case of no validation errors we perform a query
        if not rs.errors and is_search:
            query.scope = "qview_registration"
            result = self.eventproxy.submit_general_query(rs, query,
                                                          event_id=event_id)
            params['result'] = result
            if CSV:
                data = self.fill_template(rs, 'web', 'csv_search_result',
                                          params)
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
        spec = self.make_registration_query_spec(rs.ambience['event'])
        ## The following should be safe, as there are no columns which
        ## forbid NULL and are settable this way. If the aforementioned
        ## sentence is wrong all we get is a validation error in the
        ## backend.
        value = unwrap(request_extractor(
            rs, (("value", "{}_or_None".format(spec[column])),)))
        selection_params = (("row_{}".format(i), "bool")
                            for i in range(num_rows))
        selection = request_extractor(rs, selection_params)
        id_params = (("row_{}_id".format(i), "int") for i in range(num_rows))
        ids = request_extractor(rs, id_params)
        if rs.errors:
            return self.registration_query(rs, event_id, CSV=False,
                                           is_search=True)
        code = 1
        for i in range(num_rows):
            if selection["row_{}".format(i)]:
                new = {'id': ids["row_{}_id".format(i)]}
                field = column.split('.', 1)[1]
                if column.startswith("part"):
                    mo = re.search(r"^part([0-9]+)\.([a-zA-Z_]+)[0-9]+$",
                                   column)
                    part_id = int(mo.group(1))
                    field = mo.group(2)
                    new['parts'] = {part_id: {field: value}}
                elif column.startswith("fields."):
                    new['fields'] = {field: value}
                else:
                    new[field] = value
                code *= self.eventproxy.set_registration(rs, new)
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
        today = now().date()
        for part_id, part in rs.ambience['event']['parts'].items():
            if part['part_begin'] <= today and part['part_end'] >= today:
                current_part = part_id
                if part['part_end'] > today:
                    break
        else:
            current_part = None
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = {
            k: v for k, v in self.eventproxy.get_registrations(
                rs, registration_ids).items()
            if (not v['checkin']
                and (not current_part or const.RegistrationPartStati(
                    v['parts'][current_part]['status']).is_present()))}
        personas = self.coreproxy.get_event_users(rs, tuple(
            reg['persona_id'] for reg in registrations.values()))
        for registration in registrations.values():
            registration['age'] = determine_age_class(
                personas[registration['persona_id']]['birthday'],
                self.event_begin(rs.ambience['event']))
        return self.render(rs, "checkin", {
            'registrations': registrations, 'personas': personas})

    @access("event", modi={"POST"})
    @REQUESTdata(("registration_id", "id"))
    @event_guard(check_offline=True)
    def checkin(self, rs, event_id, registration_id):
        """Check a participant in."""
        if rs.errors:
            return self.checkin_form(rs, event_id)
        registration = self.eventproxy.get_registration(rs, registration_id)
        if registration['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        if registration['checkin']:
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
        if field_id is None:
            return self.render(rs, "field_set_select")
        else:
            if field_id not in rs.ambience['event']['fields']:
                return werkzeug.exceptions.NotFound("Wrong associated event.")
            return self.redirect(rs, "event/field_set_form",
                                 {'field_id': field_id})

    @access("event")
    @REQUESTdata(("field_id", "id"))
    @event_guard(check_offline=True)
    def field_set_form(self, rs, event_id, field_id):
        """Render form."""
        if field_id not in rs.ambience['event']['fields']:
            ## also catches field_id validation errors
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        personas = self.coreproxy.get_personas(
            rs, tuple(e['persona_id'] for e in registrations.values()))
        ordered = sorted(
            registrations.keys(),
            key=lambda anid: name_key(
                personas[registrations[anid]['persona_id']]))
        field_name = rs.ambience['event']['fields'][field_id]['field_name']
        values = {
            "input{}".format(registration_id):
            registration['fields'].get(field_name)
            for registration_id, registration in registrations.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "field_set", {
            'registrations': registrations, 'personas': personas,
            'ordered': ordered})

    @access("event", modi={"POST"})
    @REQUESTdata(("field_id", "id"))
    @event_guard(check_offline=True)
    def field_set(self, rs, event_id, field_id):
        """Modify a specific field on all registrations."""
        event = rs.ambience['event']
        if field_id not in event['fields']:
            ## also catches field_id validation errors
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registration_ids = self.eventproxy.list_registrations(rs, event_id)
        kind = "{}_or_None".format(event['fields'][field_id]['kind'])
        data_params = tuple(("input{}".format(registration_id), kind)
                            for registration_id in registration_ids)
        data = request_extractor(rs, data_params)
        if rs.errors:
            return self.field_set_form(rs, event_id, field_id)

        registrations = self.eventproxy.get_registrations(rs, registration_ids)
        code = 1
        field_name = event['fields'][field_id]['field_name']
        for registration_id, registration in registrations.items():
            if (data["input{}".format(registration_id)]
                    != registration['fields'].get(field_name)):
                new = {
                    'id': registration_id,
                    'fields': {
                        field_name: data["input{}".format(registration_id)]
                    }
                }
                code *= self.eventproxy.set_registration(rs, new)
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
    @REQUESTfile("json")
    def unlock_event(self, rs, event_id, json):
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        data = check(rs, "serialized_event_upload", json)
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
        if rs.ambience['event']['is_archived']:
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
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
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
    @REQUESTdata(("codes", "[int]"), ("start", "int_or_None"),
                 ("stop", "int_or_None"))
    def view_event_log(self, rs, event_id, codes, start, stop):
        """View activities concerning one event organized via DB."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.eventproxy.retrieve_log(rs, codes, event_id, start, stop)
        persona_ids = (
            {entry['submitted_by'] for entry in log if entry['submitted_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        return self.render(rs, "view_event_log", {
            'log': log, 'personas': personas,})
