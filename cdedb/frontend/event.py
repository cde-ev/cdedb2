#!/usr/bin/env python3

"""Services for the event realm."""

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, ProxyShim, connect_proxy,
    check_validation as check, persona_dataset_guard, event_guard,
    REQUESTfile, request_data_extractor)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input, Query
from cdedb.common import (
    name_key, merge_dicts, determine_age_class, deduct_years, AgeClasses,
    unwrap)
import cdedb.database.constants as const

import os
import os.path
import logging
from collections import OrderedDict
import datetime
import werkzeug
import pytz
import copy
import re
import itertools
import tempfile
import shutil
import subprocess

class EventFrontend(AbstractUserFrontend):
    """This mainly allows the organization of events."""
    realm = "event"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy": lambda obj: obj.eventproxy,
        "validator": "event_user_data",
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))

    def finalize_session(self, rs, sessiondata):
        ret = super().finalize_session(rs, sessiondata)
        if ret.is_persona:
            ret.orga = self.eventproxy.orga_info(rs, ret.persona_id)
        return ret

    def render(self, rs, templatename, params=None):
        params = params or {}
        if 'sidebar_events' not in params and "event_user" in rs.user.roles:
            params['sidebar_events'] = self.eventproxy.sidebar_events(rs)
        if 'today' not in params:
            params['today'] = datetime.datetime.now(pytz.utc).date()
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
        today = datetime.datetime.now(pytz.utc).date()
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
        return self.render(rs, "index")

    @access("event_user")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        return super().show_user(rs, persona_id, confirm_id)

    @access("event_user")
    def change_user_form(self, rs):
        return super().change_user_form(rs)

    @access("event_user", {"POST"})
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("event_admin")
    @persona_dataset_guard()
    def admin_change_user_form(self, rs, persona_id):
        return super().admin_change_user_form(rs, persona_id)

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "notes")
    @persona_dataset_guard()
    def admin_change_user(self, rs, persona_id, data):
        return super().admin_change_user(rs, persona_id, data)

    @access("event_admin")
    def create_user_form(self, rs):
        return super().create_user_form(rs)

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "notes", "username")
    def create_user(self, rs, data):
        data.update({
            'status': const.PersonaStati.event_user,
            'is_active': True,
            'cloud_account': False,
        })
        return super().create_user(rs, data)

    @access("anonymous")
    @REQUESTdata(("secret", "str"), ("username", "email"))
    def genesis_form(self, rs, case_id, secret, username):
        return super().genesis_form(rs, case_id, secret, username)

    @access("anonymous", {"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "username")
    def genesis(self, rs, case_id, secret, data):
        data.update({
            'status': const.PersonaStati.event_user,
            'is_active': True,
            'cloud_account': False,
            'notes': '',
        })
        return super().genesis(rs, case_id, secret, data)

    @access("event_admin")
    def user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_event_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        events = self.eventproxy.list_events(rs, past=True)
        choices = {'event_id': events,
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_event_user']
        return self.render(rs, "user_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries,})

    @access("event_admin")
    @REQUESTdata(("CSV", "bool"))
    def user_search(self, rs, CSV):
        """Perform search."""
        spec = QUERY_SPECS['qview_event_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.user_search_form(rs)
        query.scope = "qview_event_user"
        result = self.eventproxy.submit_general_query(rs, query)
        choices = {'gender': self.enum_choice(rs, const.Genders)}
        params = {'result': result, 'query': query, 'choices': choices}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            return self.render(rs, "user_search_result", params)

    @access("event_user")
    def show_past_event(self, rs, event_id):
        """Display concluded event."""
        event_data = self.eventproxy.get_past_event_data_one(rs, event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=True)
        participants = self.eventproxy.list_participants(rs, event_id=event_id)
        if not (rs.user.persona_id in participants or self.is_admin(rs)):
            ## make list of participants only visible to other participants
            participants = participant_data = None
        else:
            ## fix up participants, so we only see each persona once
            persona_ids = {x['persona_id'] for x in participants.values()}
            tmp = {}
            for persona_id in persona_ids:
                base_set = tuple(x for x in participants.values()
                                 if x['persona_id'] == persona_id)
                entry = {
                    'event_id': event_id,
                    'persona_id': persona_id,
                    'is_orga': any(x['is_orga'] for x in base_set),
                    'is_instructor': False,
                    }
                if any(x['course_id'] is None for x in base_set):
                    entry['course_id'] = None
                else:
                    entry['course_id'] = min(x['course_id'] for x in base_set)
                tmp[persona_id] = entry
            participants = tmp

            pd = participant_data = self.eventproxy.acquire_data(
                rs, participants.keys())
            participants = OrderedDict(sorted(
                participants.items(), key=lambda x: name_key(pd[x[0]])))
        return self.render(rs, "show_past_event", {
            'event_data': event_data, 'courses': courses,
            'participants': participants, 'participant_data': participant_data})

    @access("event_user")
    def show_past_course(self, rs, event_id, course_id):
        """Display concluded course."""
        event_data = self.eventproxy.get_past_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_past_course_data_one(rs, course_id)
        if course_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        participants = self.eventproxy.list_participants(rs,
                                                         course_id=course_id)
        if not (rs.user.persona_id in participants or self.is_admin(rs)):
            ## make list of participants only visible to other participants
            participants = participant_data = None
        else:
            pd = participant_data = self.eventproxy.acquire_data(
                rs, participants.keys())
            participants = OrderedDict(sorted(
                participants.items(), key=lambda x: name_key(pd[x[0]])))
        return self.render(rs, "show_past_course", {
            'event_data': event_data, 'course_data': course_data,
            'participants': participants, 'participant_data': participant_data})

    @access("event_admin")
    def list_past_events(self, rs):
        """List all concluded events."""
        events = self.eventproxy.list_events(rs, past=True)
        return self.render(rs, "list_past_events", {'events': events})

    @access("event_admin")
    def change_past_event_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_past_event_data_one(rs, event_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_past_event", {'data': data})

    @access("event_admin", {"POST"})
    @REQUESTdatadict("title", "organizer", "description")
    def change_past_event(self, rs, event_id, data):
        """Modify a concluded event."""
        data['id'] = event_id
        data = check(rs, "past_event_data", data)
        if rs.errors:
            return self.change_past_event_form(rs, event_id)
        num = self.eventproxy.set_past_event_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_past_event")

    @access("event_admin")
    def create_past_event_form(self, rs):
        """Render form."""
        return self.render(rs, "create_past_event")

    @access("event_admin", {"POST"})
    @REQUESTdatadict("title", "organizer", "description")
    def create_past_event(self, rs, data):
        """Add new concluded event."""
        data = check(rs, "past_event_data", data, creation=True)
        if rs.errors:
            return self.create_past_event_form(rs)
        new_id = self.eventproxy.create_past_event(rs, data)
        rs.notify("success", "Event created.")
        return self.redirect(rs, "event/show_past_event", {'event_id': new_id})

    @access("event_admin")
    def change_past_course_form(self, rs, event_id, course_id):
        """Render form."""
        event_data = self.eventproxy.get_past_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_past_course_data_one(rs, course_id)
        if course_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        merge_dicts(rs.values, course_data)
        return self.render(rs, "change_past_course", {
            'event_data': event_data, 'course_data': course_data})

    @access("event_admin", {"POST"})
    @REQUESTdatadict("title", "description")
    def change_past_course(self, rs, event_id, course_id, data):
        """Modify a concluded course."""
        data['id'] = course_id
        data = check(rs, "past_course_data", data)
        if rs.errors:
            return self.change_past_course_form(rs, event_id, course_id)
        num = self.eventproxy.set_past_course_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_past_course")

    @access("event_admin")
    def create_past_course_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_past_event_data_one(rs, event_id)
        return self.render(rs, "create_past_course", {'event_data': event_data})

    @access("event_admin", {"POST"})
    @REQUESTdatadict("title", "description")
    def create_past_course(self, rs, event_id, data):
        """Add new concluded course."""
        data['event_id'] = event_id
        data = check(rs, "past_course_data", data, creation=True)
        if rs.errors:
            return self.create_past_course_form(rs, event_id)
        new_id = self.eventproxy.create_past_course(rs, data)
        rs.notify("success", "Course created.")
        return self.redirect(rs, "event/show_past_course",
                             {'course_id': new_id})

    @access("event_admin", {"POST"})
    def delete_past_course(self, rs, event_id, course_id):
        """Delete a concluded course.

        This also deletes all participation information w.r.t. this course.
        """
        num = self.eventproxy.delete_past_course(rs, course_id, cascade=True)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_past_event")

    @access("event_admin", {"POST"})
    @REQUESTdata(("course_id", "int_or_None"), ("persona_id", "cdedbid"),
                 ("is_instructor", "bool"), ("is_orga", "bool"))
    def add_participant(self, rs, event_id, course_id, persona_id,
                        is_instructor, is_orga):
        """Add participant to concluded event."""
        if rs.errors:
            return self.show_past_course(rs, event_id, course_id)
        num = self.eventproxy.create_participant(
            rs, event_id, course_id, persona_id, is_instructor, is_orga)
        self.notify_integer_success(rs, num)
        if course_id:
            return self.redirect(rs, "event/show_past_course",
                                 {'course_id': course_id})
        else:
            return self.redirect(rs, "event/show_past_event")

    @access("event_admin", {"POST"})
    @REQUESTdata(("persona_id", "int"), ("course_id", "int_or_None"))
    def remove_participant(self, rs, event_id, persona_id, course_id):
        """Remove participant."""
        if rs.errors:
            return self.show_event(rs, event_id)
        num = self.eventproxy.delete_participant(
            rs, event_id, course_id, persona_id)
        self.notify_integer_success(rs, num)
        if course_id:
            return self.redirect(rs, "event/show_past_course", {
                'course_id': course_id})
        else:
            return self.redirect(rs, "event/show_past_event")

    @access("event_admin")
    def list_events(self, rs):
        """List all events organized via DB."""
        events = self.eventproxy.list_events(rs, past=False)
        data = self.eventproxy.get_event_data(rs, events.keys())
        return self.render(rs, "list_events", {'data': data})

    @access("event_user")
    def show_event(self, rs, event_id):
        """Display event organized via DB."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        event_data['is_open'] = self.is_open(event_data)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        if courses:
            course_data = self.eventproxy.get_course_data(rs, courses.keys())
        else:
            course_data = None
        return self.render(rs, "show_event", {
            'event_data': event_data, 'course_data': course_data,
            'locked': self.is_locked(event_data)})

    @access("event_user")
    @event_guard()
    def event_config(self, rs, event_id):
        """Overview of properties of an event organized via DB."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        merge_dicts(rs.values, data)
        orgas = self.eventproxy.acquire_data(rs, data['orgas'])
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        return self.render(rs, "event_config", {
            'data': data, 'orgas': orgas, 'locked': self.is_locked(data),
            'questionnaire': questionnaire,
            'minor_form_present': minor_form_present})

    @access("event_user")
    @event_guard(check_offline=True)
    def change_event_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_event", {'data': data})

    @access("event_user", {"POST"})
    @REQUESTdatadict(
        "title", "organizer", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "iban", "use_questionnaire", "notes")
    @event_guard(check_offline=True)
    def change_event(self, rs, event_id, data):
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, "event_data", data)
        if rs.errors:
            return self.change_event_form(rs, event_id)
        num = self.eventproxy.set_event_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user")
    def get_minor_form(self, rs, event_id):
        """Retrieve minor form."""
        path = os.path.join(self.conf.STORAGE_DIR, "minor_form", str(event_id))
        return self.send_file(
            rs, mimetype="application/pdf",
            filename=self.i18n("minor_form.pdf", rs.lang), path=path)

    @access("event_user", {"POST"})
    @REQUESTfile("minor_form")
    @event_guard(check_offline=True)
    def change_minor_form(self, rs, event_id, minor_form):
        """Replace the form for parental agreement for minors.

        This somewhat clashes with our usual naming convention, it is
        about the 'minor form' and not about changing minors.
        """
        minor_form = check(rs, 'pdffile', minor_form, "minor_form")
        if rs.errors:
            return self.event_config(rs, event_id)
        blob = minor_form.read()
        path = os.path.join(self.conf.STORAGE_DIR, 'minor_form', str(event_id))
        with open(path, 'wb') as f:
            f.write(blob)
        rs.notify("success", "Form updated.")
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdata(("orga_id", "cdedbid"))
    @event_guard(check_offline=True)
    def add_orga(self, rs, event_id, orga_id):
        """Make an additional persona become orga."""
        if rs.errors:
            return self.event_config(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] | {orga_id}
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdata(("orga_id", "int"))
    @event_guard(check_offline=True)
    def remove_orga(self, rs, event_id, orga_id):
        """Demote a persona.

        This can drop your own orga role.
        """
        if rs.errors:
            return self.event_config(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] - {orga_id}
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user")
    @event_guard(check_offline=True)
    def change_part_form(self, rs, event_id, part_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        if part_id not in data['parts']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        merge_dicts(rs.values, data['parts'][part_id])
        return self.render(rs, "change_part", {'data': data})

    @access("event_user", {"POST"})
    @REQUESTdatadict("title", "part_begin", "part_end", "fee")
    @event_guard(check_offline=True)
    def change_part(self, rs, event_id, part_id, data):
        """Update an event part."""
        data = check(rs, "event_part_data", data)
        if rs.errors:
            return self.change_part_form(rs, event_id, part_id)
        newdata = {
            'id': event_id,
            'parts': {
                part_id: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdatadict("part_title", "part_begin", "part_end", "fee")
    @event_guard(check_offline=True)
    def add_part(self, rs, event_id, data):
        """Create a new event part."""
        ## fix up name collision
        data['title'] = data['part_title']
        del data['part_title']
        data = check(rs, "event_part_data", data)
        if rs.errors:
            return self.event_config(rs, event_id)
        newdata = {
            'id': event_id,
            'parts': {
                -1: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user")
    @event_guard(check_offline=True)
    def change_field_form(self, rs, event_id, field_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        if field_id not in data['fields']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        field_data = data['fields'][field_id]
        if 'entries' not in rs.values:
            ## format the entries value
            rs.values['entries'] = "\n".join(";".join(x for x in e)
                                             for e in field_data['entries'])
        merge_dicts(rs.values, field_data)
        return self.render(rs, "change_field", {'data': data})

    @access("event_user", {"POST"})
    @REQUESTdatadict("kind", "entries")
    @event_guard(check_offline=True)
    def change_field(self, rs, event_id, field_id, data):
        """Update an event data field (for questionnaire etc.)."""
        data = check(rs, "event_field_data", data)
        if rs.errors:
            return self.change_field_form(rs, event_id, field_id)
        newdata = {
            'id': event_id,
            'fields': {
                field_id: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdatadict("field_name", "kind", "entries")
    @event_guard(check_offline=True)
    def add_field(self, rs, event_id, data):
        """Create a new field to attach information to a registration."""
        data = check(rs, "event_field_data", data, creation=True)
        if rs.errors:
            return self.event_config(rs, event_id)
        newdata = {
            'id': event_id,
            'fields': {
                -1: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdata(("field_id", "int"))
    @event_guard(check_offline=True)
    def remove_field(self, rs, event_id, field_id):
        """Delete a field.

        This does not delete the associated information allready
        submitted, but makes it inaccessible.
        """
        if rs.errors:
            return self.event_config(rs, event_id)
        data = {
            'id': event_id,
            'fields': {
                field_id: None
            }
        }
        num = self.eventproxy.set_event_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_admin")
    def create_event_form(self, rs):
        """Render form."""
        return self.render(rs, "create_event")

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "organizer", "description", "shortname",
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
        rs.notify("success", "Event created.")
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event_user")
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        params = {'event_data': event_data, 'course_data': course_data,
                  'locked': self.is_locked(event_data)}
        if event_id in rs.user.orga or self.is_admin(rs):
            registrations = self.eventproxy.list_registrations(rs, event_id)
            registration_data = {
                k: v for k, v in self.eventproxy.get_registrations(
                    rs, registrations).items()
                if any(pdata['course_id'] == course_id
                       or pdata['course_instructor'] == course_id
                       for pdata in v['parts'].values())}
            user_data = self.eventproxy.acquire_data(
                rs, tuple(e['persona_id'] for e in registration_data.values()))
            attendees = self.calculate_groups(
                (course_id,), event_data, registration_data, key="course_id",
                user_data=user_data)
            params['user_data'] = user_data
            params['registration_data'] = registration_data
            params['attendees'] = attendees
        return self.render(rs, "show_course", params)

    @access("event_user")
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

    @access("event_user", {"POST"})
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
        num = self.eventproxy.set_course_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_course")

    @access("event_user")
    @event_guard(check_offline=True)
    def create_course_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        ## by default select all parts
        if 'parts' not in rs.values:
            rs.values.setlist('parts', data['parts'])
        return self.render(rs, "create_course", {'data': data})

    @access("event_user", {"POST"})
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
        rs.notify("success", "Course created.")
        return self.redirect(rs, "event/show_course", {'course_id': new_id})

    @access("event_user")
    @event_guard()
    def summary(self, rs, event_id):
        """Present an overview of the basic stats."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        user_data = self.eventproxy.acquire_data(
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
        tests = {
            'not payed': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_involved
                and not rdata['payment'])),
            'pending': (lambda edata, rdata, pdata: (
                pdata['status'] == stati.applied
                and rdata['payment'])),
            'no parental agreement': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_involved
                and get_age(user_data[rdata['persona_id']]).is_minor()
                and not rdata['parental_agreement'])),
            'no lodgement': (lambda edata, rdata, pdata: (
                stati(pdata['status']).is_present
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
            for key, test in tests.items()
        }
        return self.render(rs, "summary", {
            'event_data': event_data, 'registration_data': registration_data,
            'user_data': user_data, 'courses': courses,
            'statistics': statistics, 'listings': listings})

    @access("event_user")
    @REQUESTdata(("course_id", "int_or_None"))
    @event_guard()
    def course_choices(self, rs, event_id, course_id):
        """List course choices.

        If course_id is not provided an overview of the number of choices
        for all courses is presented. Otherwise all votes for a specific
        course are listed.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses)
        ## this if handles validation errors
        if course_id not in courses:
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
            return self.render(rs, "course_choices_overview", {
                'event_data': event_data, 'course_data': course_data,
                'counts': counts})
        else:
            user_data = self.eventproxy.acquire_data(rs, tuple(
                rdata['persona_id'] for rdata in registration_data.values()))
            sorter = lambda registration_id: name_key(
                user_data[registration_data[registration_id]['persona_id']])
            candidates = {
                (part_id, i): sorted(
                    (registration_id
                     for registration_id, rdata in registration_data.items()
                     if (len(rdata['choices'][part_id]) > i
                         and rdata['choices'][part_id][i] == course_id
                         and (rdata['parts'][part_id]['status']
                              == const.RegistrationPartStati.participant)
                         and rdata['persona_id'] not in event_data['orgas'])),
                    key=sorter)
                for part_id in event_data['parts']
                for i in range(3)
            }
            return self.render(rs, "course_choices_single", {
                'event_data': event_data, 'course_data': course_data,
                'candidates': candidates, 'user_data': user_data,
                'registration_data': registration_data,})

    @access("event_user")
    @event_guard()
    def downloads(self, rs, event_id):
        """Offer documents like nametags for download."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        return self.render(rs, "downloads", {'event_data': event_data})

    @access("event_user")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_nametags(self, rs, event_id, runs):
        """Create nametags.

        You probably want to edit the provided tex file.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        for rdata in registration_data.values():
            rdata['age'] = determine_age_class(
                user_data[rdata['persona_id']]['birthday'],
                min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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

    @access("event_user")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_puzzle(self, rs, event_id, runs):
        """Aggregate course choice information.

        This can be printed and cut to help with distribution of participants.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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
            'event_data': event_data, 'course_data': course_data, 'counts': counts,
            'registration_data': registration_data, 'user_data': user_data})
        return self.serve_latex_document(rs, tex, "course_puzzle", runs)

    @access("event_user")
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
        user_data = self.eventproxy.acquire_data(rs, tuple(
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

    @access("event_user")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_course_lists(self, rs, event_id, runs):
        """Create lists to post to course rooms."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        attendees = self.calculate_groups(
            courses, event_data, registration_data, key="course_id",
            user_data=user_data)
        tex = self.fill_template(rs, "tex", "course_lists", {
            'event_data': event_data, 'course_data': course_data,
            'registration_data': registration_data, 'user_data': user_data,
            'attendees': attendees})
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

    @access("event_user")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_lodgement_lists(self, rs, event_id, runs):
        """Create lists to post to lodgements."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            lodgements, event_data, registration_data, key="lodgement_id",
            user_data=user_data)
        tex = self.fill_template(rs, "tex", "lodgement_lists", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants})
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

    @access("event_user")
    @REQUESTdata(("runs", "single_digit_int"))
    @event_guard()
    def download_participant_list(self, rs, event_id, runs):
        """Create list to send to all participants."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = {
            k: v
            for k, v in self.eventproxy.get_registrations(
                rs, registrations).items()
            if any(pdata['status'] == const.RegistrationPartStati.participant
                   for pdata in v['parts'].values())}
        user_data = self.eventproxy.acquire_data(
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

    @access("event_user")
    @event_guard()
    def download_expuls(self, rs, event_id):
        """Create TeX-snippet for announcement in the ExPuls."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses)
        tex = self.fill_template(rs, "tex", "expuls", {
            'event_data': event_data, 'course_data': course_data})
        return self.send_file(rs, data=tex,
                              filename=self.i18n("expuls.tex", rs.lang))

    @access("event_user")
    @event_guard()
    def download_export(self, rs, event_id):
        """Retrieve all data for this event to initialize an offline instance."""
        raise NotImplementedError("TODO")

    @access("event_user")
    def register_form(self, rs, event_id):
        """Render form."""
        registrations = self.eventproxy.list_registrations(
            rs, event_id, persona_id=rs.user.persona_id)
        if rs.user.persona_id in registrations.values():
            registration_id = next(i for i in registrations)
            rs.notify("info", "Allready registered.")
            return self.redirect(rs, "event/registration_status")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not self.is_open(event_data):
            rs.notify("warning", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(event_data):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/show_event")
        user_data = self.eventproxy.acquire_data_one(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        if not minor_form_present and age.is_minor():
            rs.notify("info", "No minors may register.")
            return self.redirect(rs, "event/show_event")
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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
                if const.RegistrationPartStati(entry['status']).is_involved)
        choice_params = (("course_choice{}_{}".format(part_id, i), "int")
                         for part_id in standard_data['parts'] for i in range(3))
        choices = request_data_extractor(rs, choice_params)
        instructor_params = (
            ("course_instructor{}".format(part_id), "int_or_None")
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

    @access("event_user", {"POST"})
    def register(self, rs, event_id):
        """Register for an event."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if not self.is_open(event_data):
            rs.notify("error", "Registration not open.")
            return self.redirect(rs, "event/show_event")
        if self.is_locked(event_data):
            rs.notify("error", "Event locked.")
            return self.redirect(rs, "event/show_event")
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        registration_data = self.process_registration_input(rs, event_data,
                                                            course_data)
        if rs.errors:
            return self.register_form(rs, event_id)
        registration_data['event_id'] = event_data['id']
        registration_data['persona_id'] = rs.user.persona_id
        user_data = self.eventproxy.acquire_data_one(rs, rs.user.persona_id)
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
                  if const.RegistrationPartStati(entry['status']).is_involved)
        self.do_mail(
            rs, "register",
            {'To': (rs.user.username,),
             'Subject': 'Registered for event {}'.format(event_data['title'])},
            {'user_data': user_data, 'event_data': event_data, 'fee': fee,
             'age': age})
        rs.notify("success", "Registered for event.")
        return self.redirect(rs, "event/registration_status")

    @access("event_user")
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
        user_data = self.eventproxy.acquire_data_one(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        fee = sum(event_data['parts'][part_id]['fee']
                  for part_id, entry in registration_data['parts'].items()
                  if const.RegistrationPartStati(entry['status']).is_involved)
        return self.render(rs, "registration_status", {
            'registration_data': registration_data, 'event_data': event_data,
            'user_data': user_data, 'age': age, 'course_data': course_data,
            'fee': fee})

    @access("event_user")
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
        today = datetime.datetime.now(pytz.utc).date()
        if (event_data['registration_soft_limit'] and
                today > event_data['registration_soft_limit']):
            rs.notify("warning", "Registration closed, no changes possible.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("warning", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        user_data = self.eventproxy.acquire_data_one(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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

    @access("event_user", {"POST"})
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
        today = datetime.datetime.now(pytz.utc).date()
        if (event_data['registration_soft_limit'] and
                today > event_data['registration_soft_limit']):
            rs.notify("error", "No changes allowed anymore.")
            return self.redirect(rs, "event/registration_status")
        if self.is_locked(event_data):
            rs.notify("error", "Event locked.")
            return self.redirect(rs, "event/registration_status")
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        stored_data = self.eventproxy.get_registration(rs, registration_id)
        registration_data = self.process_registration_input(
            rs, event_data, course_data, parts=stored_data['parts'])
        if rs.errors:
            return self.amend_registration_form(rs, event_id, registration_id)

        registration_data['id'] = registration_id
        user_data = self.eventproxy.acquire_data_one(rs, rs.user.persona_id)
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        registration_data['mixed_lodging'] = (registration_data['mixed_lodging']
                                              and age.may_mix())
        num = self.eventproxy.set_registration(rs, registration_data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/registration_status")

    @access("event_user")
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
            'event_data': event_data, 'questionnaire': questionnaire,
            'locked': self.is_locked(event_data)})

    @access("event_user", {"POST"})
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
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
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
            return self.questionnaire_form(rs, event_id, registration_id)

        num = self.eventproxy.set_registration(rs, {
            'id': registration_id, 'field_data': data,})
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/questionnaire_form")

    @access("event_user")
    @event_guard(check_offline=True)
    def change_questionnaire_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        current = {
            "{}_{}".format(key, i): value
            for i, entry in enumerate(questionnaire)
            for key, value in entry.items()}
        merge_dicts(rs.values, current)
        return self.render(rs, "change_questionnaire", {
            'event_data': event_data, 'questionnaire': questionnaire})

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
        spec = {
                'field_id': "int_or_None",
                'title': "str_or_None",
                'info': "str_or_None",
                'input_size': "int_or_None",
                'readonly': "bool_or_None",
        }
        params = tuple(x
            for i in range(num)
            for x in (("{}_{}".format(key, i), value)
                      for key, value in spec.items()))
        data = request_data_extractor(rs, params)
        questionnaire = tuple(
            {key: data["{}_{}".format(key, i)] for key in spec}
            for i in range(num)
        )
        return questionnaire

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def change_questionnaire(self, rs, event_id):
        """Configure the questionnaire.

        This allows the orgas to design a form without interaction with an
        administrator. This assumes, that the number of rows stays constant
        and only the attributes of the rows are changed. For more/less rows
        there are seperate functions.
        """
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        new_questionnaire = self.process_questionnaire_input(
            rs, len(questionnaire))
        if rs.errors:
            return self.change_questionnaire_form(rs, event_id)
        num = self.eventproxy.set_questionnaire(rs, event_id, new_questionnaire)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

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

    @access("event_user")
    @event_guard(check_offline=True)
    def reorder_questionnaire_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        return self.render(rs, "reorder_questionnaire", {
            'event_data': event_data, 'questionnaire': questionnaire})

    @access("event_user", {"POST"})
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
        num = self.eventproxy.set_questionnaire(rs, event_id, new_questionnaire)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @REQUESTdatadict('row_field_id', 'row_title', 'row_info', 'row_input_size',
                     'row_readonly',)
    @event_guard(check_offline=True)
    def add_questionnaire_row(self, rs, event_id, data):
        """Append a row to the orga designed form."""
        ## fix up name collision
        data = ({key: data["row_{}".format(key)]
                 for key in ('field_id', 'title', 'info', 'input_size',
                             'readonly',)},)
        data = check(rs, "questionnaire_data", data)
        if rs.errors:
            return self.event_config(rs, event_id)
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        new_questionnaire = tuple(self._sanitize_questionnaire_row(row)
                                  for row in questionnaire) + tuple(data)
        num = self.eventproxy.set_questionnaire(rs, event_id, new_questionnaire)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def remove_questionnaire_row(self, rs, event_id, num):
        """Zap a row from the orga designed form."""
        questionnaire = self.eventproxy.get_questionnaire(rs, event_id)
        new_questionnaire = tuple(
            self._sanitize_questionnaire_row(row)
            for i, row in enumerate(questionnaire) if i != num)
        num = self.eventproxy.set_questionnaire(rs, event_id, new_questionnaire)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/event_config")


    @access("event_user")
    @event_guard()
    def show_registration(self, rs, event_id, registration_id):
        """Display all information pertaining to one registration."""
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if event_id != registration_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        user_data = self.eventproxy.acquire_data_one(
            rs, registration_data['persona_id'])
        age = determine_age_class(
            user_data['birthday'],
            min(p['part_begin'] for p in event_data['parts'].values()))
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        return self.render(rs, "show_registration", {
            'registration_data': registration_data, 'event_data': event_data,
            'user_data': user_data, 'age': age, 'course_data': course_data,
            'lodgement_data': lodgement_data,
            'locked': self.is_locked(event_data)})

    @access("event_user")
    @event_guard(check_offline=True)
    def change_registration_form(self, rs, event_id, registration_id):
        """Render form."""
        registration_data = self.eventproxy.get_registration(rs,
                                                             registration_id)
        if event_id != registration_data['event_id']:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        user_data = self.eventproxy.acquire_data_one(
            rs, registration_data['persona_id'])
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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
        merge_dicts(rs.values, reg_values, field_values, *part_values)
        return self.render(rs, "change_registration", {
            'registration_data': registration_data, 'event_data': event_data,
            'user_data': user_data, 'course_data': course_data,
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
            part_params.append(("{}.status".format(prefix), "int"))
            part_params.extend(
                ("{}.{}".format(prefix, suffix), "int_or_None")
                for suffix in ("status", "course_id", "course_choice_0",
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

    @access("event_user", {"POST"})
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
        num = self.eventproxy.set_registration(rs, registration_data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_registration")

    @access("event_user")
    @event_guard(check_offline=True)
    def add_registration_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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

    @access("event_user", {"POST"})
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
                    rs, (persona_id,), tuple(const.EVENT_STATI))):
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
        self.notify_integer_success(rs, new_id)
        return self.redirect(rs, "event/show_registration",
                             {'registration_id': new_id})

    @staticmethod
    def calculate_groups(entity_ids, event_data, registration_data, key,
                         user_data=None):
        """Determine inhabitants/attendees of lodgements/courses.

        This has to take care only to select registrations which are
        actually present (and not cancelled or such).

        :type entity_ids: [int]
        :type event_data: {str: object}
        :type registration_data: {int: {str: object}}
        :type key: str
        :param key: one of lodgement_id or course_id, signalling what to do
        :type user_data: {int: {str: object}} or None
        :param user_data: If provided this is used to sort the resulting
          lists by name, so that the can be displayed sorted.
        :rtype: {(int, int): [int]}
        """
        def _check_belonging(entity_id, part_id, registration_id):
            """The actual check, un-inlined."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (pdata[key] == entity_id
                    and const.RegistrationPartStati(pdata['status']).is_present)
        if user_data is None:
            sorter = lambda x: x
        else:
            sorter = lambda anid: name_key(
                user_data[registration_data[anid]['persona_id']])
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
                        and len(group) - ldata['capacity'] != _reserve(group,
                                                                       part_id)
                        and ((len(group) - ldata['capacity'] > 0)
                             or _reserve(group))):
                    ret.append(_reserve_problem(lodgement_id, part_id))
        return ret

    @access("event_user")
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
        user_data = self.eventproxy.acquire_data(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            lodgements, event_data, registration_data, key="lodgement_id")

        problems = self.check_lodgment_problems(
            event_data, lodgement_data, registration_data, user_data,
            inhabitants)

        return self.render(rs, "lodgements", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants, 'problems': problems,
            'locked': self.is_locked(event_data)})

    @access("event_user")
    @event_guard()
    def show_lodgement(self, rs, event_id, lodgement_id):
        """Display details of one lodgement."""
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
        user_data = self.eventproxy.acquire_data(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), event_data, registration_data, key="lodgement_id",
            user_data=user_data)

        plural_data = {lodgement_id: lodgement_data}
        problems = self.check_lodgment_problems(
            event_data, plural_data, registration_data, user_data,
            inhabitants)

        return self.render(rs, "show_lodgement", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants, 'problems': problems,
            'locked': self.is_locked(event_data)})

    @access("event_user")
    @event_guard(check_offline=True)
    def create_lodgement_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        return self.render(rs, "create_lodgement", {'event_data': event_data})

    @access("event_user", {"POST"})
    @REQUESTdatadict("moniker", "capacity", "reserve", "notes")
    @event_guard(check_offline=True)
    def create_lodgement(self, rs, event_id, data):
        """Add a new lodgement."""
        data['event_id'] = event_id
        data = check(rs, "lodgement_data", data, creation=True)
        if rs.errors:
            return self.create_lodgement_form(rs, event_id)

        new_id = self.eventproxy.create_lodgement(rs, data)
        self.notify_integer_success(rs, new_id)
        return self.redirect(rs, "event/show_lodgement",
                             {'lodgement_id': new_id})

    @access("event_user")
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

    @access("event_user", {"POST"})
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

        num = self.eventproxy.set_lodgement(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_lodgement")

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def delete_lodgement(self, rs, event_id, lodgement_id):
        """Remove a lodgement.

        For this the lodgement has to be empty, otherwise we errer out.
        """
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        if lodgement_data['event_id'] != event_id:
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        if any(pdata['lodgement_id'] == lodgement_id
               for rdata in registration_data.values()
               for pdata in rdata['parts'].values()):
            ## In contrast to calculate_groups this also takes rejected
            ## and cancelled entries into account.
            rs.notify("error", "Lodgement not empty (includes non-participants!).")
            return self.redirect(rs, "event/show_lodgement")

        num = self.eventproxy.delete_lodgement(rs, lodgement_id)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/lodgements")

    @access("event_user")
    @event_guard(check_offline=True)
    def manage_inhabitants_form(self, rs, event_id, lodgement_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        inhabitants = self.calculate_groups(
            (lodgement_id,), event_data, registration_data, key="lodgement_id",
            user_data=user_data)
        def _check_without_lodgement(registration_id, part_id):
            """Un-inlined check for registration without lodgement."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(pdata['status']).is_present
                    and not pdata['lodgement_id'])
        without_lodgement = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_without_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
                    user_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        def _check_with_lodgement(registration_id, part_id):
            """Un-inlined check for registration with different lodgement."""
            pdata = registration_data[registration_id]['parts'][part_id]
            return (const.RegistrationPartStati(pdata['status']).is_present
                    and pdata['lodgement_id']
                    and pdata['lodgement_id'] != lodgement_id)
        with_lodgement = {
            part_id: sorted(
                (registration_id
                 for registration_id, rdata in registration_data.items()
                 if _check_with_lodgement(registration_id, part_id)),
                key=lambda anid: name_key(
                    user_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        return self.render(rs, "manage_inhabitants", {
            'event_data': event_data, 'lodgement_data': lodgement_data,
            'registration_data': registration_data, 'user_data': user_data,
            'inhabitants': inhabitants, 'without_lodgement': without_lodgement,
            'with_lodgement': with_lodgement})

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def manage_inhabitants(self, rs, event_id, lodgement_id):
        """Alter who is assigned to a lodgement.

        This tries to be a bit smart and write only changed state.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgement(rs, lodgement_id)
        params = tuple(("inhabitants_{}".format(part_id), "int_csv_list")
                       for part_id in event_data['parts'])
        data = request_data_extractor(rs, params)
        if rs.errors:
            return self.manage_inhabitants_form(rs, event_id, lodgement_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        num = 1
        for registration_id, rdata in registration_data.items():
            new_reg = {
                'id': registration_id,
                'parts': {},
            }
            for part_id in event_data['parts']:
                inhabits = (registration_id
                            in data["inhabitants_{}".format(part_id)])
                if (inhabits
                    != (lodgement_id == rdata['parts'][part_id]['lodgement_id'])):
                    new_reg['parts'][part_id] = {
                        'lodgement_id': (lodgement_id if inhabits else None)
                    }
            if new_reg['parts']:
                num *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_lodgement")

    @access("event_user")
    @event_guard(check_offline=True)
    def manage_attendees_form(self, rs, event_id, course_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        attendees = self.calculate_groups(
            (course_id,), event_data, registration_data, key="course_id",
            user_data=user_data)
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
                    user_data[registration_data[anid]['persona_id']])
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
                    user_data[registration_data[anid]['persona_id']])
            )
            for part_id in event_data['parts']
        }
        return self.render(rs, "manage_attendees", {
            'event_data': event_data, 'course_data': course_data,
            'registration_data': registration_data, 'user_data': user_data,
            'attendees': attendees, 'without_course': without_course,
            'with_course': with_course})

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def manage_attendees(self, rs, event_id, course_id):
        """Alter who is assigned to this course."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        params = tuple(("attendees_{}".format(part_id), "int_csv_list")
                       for part_id in course_data['parts'])
        data = request_data_extractor(rs, params)
        if rs.errors:
            return self.manage_attendees_form(rs, event_id, course_id)
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        num = 1
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
                num *= self.eventproxy.set_registration(rs, new_reg)
        self.notify_integer_success(rs, num)
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
            spec["part{0}.course_id{0}".format(part_id)] = "int"
            spec["part{0}.status{0}".format(part_id)] = "int"
            spec["part{0}.lodgement_id{0}".format(part_id)] = "int"
            spec["part{0}.course_instructor{0}".format(part_id)] = "int"
        spec[",".join("part{0}.course_id{0}".format(part_id)
                      for part_id in event_data['parts'])] = "int"
        spec[",".join("part{0}.status{0}".format(part_id)
                      for part_id in event_data['parts'])] = "int"
        spec[",".join("part{0}.lodgement{0}".format(part_id)
                      for part_id in event_data['parts'])] = "int"
        spec[",".join("part{0}.course_instructor{0}".format(part_id)
                     for part_id in event_data['parts'])] = "int"
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

    @access("event_user")
    @event_guard()
    def registration_query(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        spec = self.make_registration_query_spec(event_data)
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)

        courses = self.eventproxy.list_courses(rs, event_id, past=False)
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
              deduct_years(datetime.datetime.now(pytz.utc).date(), 18)),),
            (("user_data.birthday", True), ("reg.id", True)),)
        return self.render(rs, "registration_query", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries, 'titles': titles,
            'event_data': event_data})

    @access("event_user")
    @REQUESTdata(("CSV", "bool"))
    @event_guard()
    def registration_query_result(self, rs, event_id, CSV):
        """Generate custom data sets from registration data.

        This is a pretty versatile method building on the query module.
        """
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        spec = self.make_registration_query_spec(event_data)
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.registration_query(rs, event_id)

        query.scope = "qview_registration"
        result = self.eventproxy.submit_general_query(rs, query,
                                                      event_id=event_id)
        courses = self.eventproxy.list_courses(rs, event_id, past=False)
        course_data = self.eventproxy.get_course_data(rs, courses.keys())
        lodgements = self.eventproxy.list_lodgements(rs, event_id)
        lodgement_data = self.eventproxy.get_lodgements(rs, lodgements)
        choices, titles = self.make_registracion_query_aux(
            rs, event_data, course_data, lodgement_data)
        params = {'result': result, 'query': query, 'choices': choices,
                  'titles': titles}

        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            params.update({
                'choices': choices,
                'titles': titles,
                'event_data': event_data,
                'spec': spec,
                'locked': self.is_locked(event_data)})
            return self.render(rs, "registration_query_result", params)

    @access("event_user", {"POST"})
    @REQUESTdata(("column", "str"), ("num_rows", "int"))
    @event_guard(check_offline=True)
    def registration_query_action(self, rs, event_id, column, num_rows):
        """Apply changes to a selection of registrations."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        spec = self.make_registration_query_spec(event_data)
        value = request_data_extractor(rs, (("value", spec[column]),))['value']
        selection_params = (("row_{}".format(i), "bool")
                            for i in range(num_rows))
        selection_data = request_data_extractor(rs, selection_params)
        id_params = (("row_{}_id".format(i), "int") for i in range(num_rows))
        id_data = request_data_extractor(rs, id_params)
        if rs.errors:
            return self.registration_query_result(rs, event_id, CSV=False)
        success = 1
        for i in range(num_rows):
            if selection_data["row_{}".format(i)]:
                new_data = {'id': id_data["row_{}_id".format(i)]}
                field = column.split('.', 1)[1]
                if column.startswith("part"):
                    mo = re.search("^part([0-9]+)\.([a-zA-Z_]+)[0-9]+$", column)
                    part_id = int(mo.group(1))
                    field = mo.group(2)
                    new_data['parts'] = {part_id: {field: value}}
                elif column.startswith("fields."):
                    new_data['field_data'] = {field: value}
                else:
                    new_data[field] = value
                success *= self.eventproxy.set_registration(rs, new_data)
        self.notify_integer_success(rs, success)
        params = {key: value for key, value in rs.request.values.items()
                  if key.startswith(("qsel_", "qop_", "qval_", "qord_"))}
        params['CSV'] = False
        return self.redirect(rs, "event/registration_query_result", params)

    @access("event_user")
    @event_guard(check_offline=True)
    def checkin_form(self, rs, event_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        today = datetime.datetime.now(pytz.utc).date()
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
                    v['parts'][current_part]['status']).is_present))}
        user_data = self.eventproxy.acquire_data(rs, tuple(
            rdata['persona_id'] for rdata in registration_data.values()))
        for rdata in registration_data.values():
            rdata['age'] = determine_age_class(
                user_data[rdata['persona_id']]['birthday'],
                min(p['part_begin'] for p in event_data['parts'].values()))
        return self.render(rs, "checkin", {
            'event_data': event_data, 'registration_data': registration_data,
            'user_data': user_data})

    @access("event_user", {"POST"})
    @REQUESTdata(("registration_id", "int"))
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
            'checkin': datetime.datetime.now(pytz.utc),
        }
        num = self.eventproxy.set_registration(rs, new_reg)
        self.notify_integer_success(rs, num)
        return self.checkin_form(rs, event_id)

    @access("event_user")
    @REQUESTdata(("field_id", "int_or_None"))
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

    @access("event_user")
    @REQUESTdata(("field_id", "int"))
    @event_guard(check_offline=True)
    def field_set_form(self, rs, event_id, field_id):
        """Render form."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        if field_id not in event_data['fields']:
            ## also catches field_id validation errors
            return werkzeug.exceptions.NotFound("Wrong associated event.")
        registrations = self.eventproxy.list_registrations(rs, event_id)
        registration_data = self.eventproxy.get_registrations(rs, registrations)
        user_data = self.eventproxy.acquire_data(
            rs, tuple(e['persona_id'] for e in registration_data.values()))
        ordered = sorted(
            registration_data.keys(),
            key=lambda anid: name_key(
                user_data[registration_data[anid]['persona_id']]))
        field_name = event_data['fields'][field_id]['field_name']
        values = {
            "input{}".format(registration_id):
            rdata['field_data'].get(field_name)
            for registration_id, rdata in registration_data.items()}
        merge_dicts(rs.values, values)
        return self.render(rs, "field_set", {
            'event_data': event_data, 'registration_data': registration_data,
            'user_data': user_data, 'ordered': ordered})

    @access("event_user", {"POST"})
    @REQUESTdata(("field_id", "int"))
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
        num = 1
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
                num *= self.eventproxy.set_registration(rs, new_data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/show_event")

    @access("event_user", {"POST"})
    @event_guard(check_offline=True)
    def lock_event(self, rs, event_id):
        """Lock an event for offline usage."""
        raise NotImplementedError("TODO")

    @access("event_admin", {"POST"})
    # TODO REQUESTfile
    def unlock_event(self, rs, event_id):
        """Unlock an event after offline usage and incorporate the offline
        changes."""
        raise NotImplementedError("TODO")

