#!/usr/bin/env python3

"""Services for the event realm."""

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, access, ProxyShim, connect_proxy,
    check_validation as check, persona_dataset_guard, event_guard,
    REQUESTfile)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, QueryOperators, mangle_query_input
from cdedb.common import name_key, merge_dicts
import cdedb.database.constants as const

import os.path
import logging
from collections import OrderedDict
import datetime
import werkzeug

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
        return super().render(rs, templatename, params=params)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def is_orga(rs, event_id):
        """Small helper to determine if we are orga.

        This is somewhat analoguous to
        :py:meth:`cdedb.backend.event.EventBackend.is_orga`.

        :type rs: :py:class:`FrontendRequestState`
        :type event_id: int
        :rtype: bool
        """
        return event_id in rs.user.orga

    @staticmethod
    def is_open(event_data):
        """Small helper to determine if an event is open for registration.

        This is a somewhat verbose condition encapsulated here for brevity.

        :type event_data: {str: object}
        :param event_data: event dataset as returned by the backend
        :rtype: bool
        """
        today = datetime.datetime.now().date()
        return (event_data['registration_start']
                and event_data['registration_start'] <= today
                and (event_data['registration_hard_limit'] is None
                     or event_data['registration_hard_limit'] >= today))

    @access("persona")
    def index(self, rs):
        """Render start page."""
        return self.render(rs, "index")

    @access("event_user")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        return super().show_user(rs, persona_id, confirm_id)

    @access("event_user")
    @persona_dataset_guard()
    def change_user_form(self, rs, persona_id):
        return super().change_user_form(rs, persona_id)

    @access("event_user", {"POST"})
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country")
    @persona_dataset_guard()
    def change_user(self, rs, persona_id, data):
        return super().change_user(rs, persona_id, data)

    @access("event_admin")
    @persona_dataset_guard()
    def admin_change_user_form(self, rs, persona_id):
        """Render form."""
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
        """Render form."""
        return super().create_user_form(rs)

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "notes", "username")
    def create_user(self, rs, data):
        """Create new user account."""
        data.update({
            'status': const.PersonaStati.event_user,
            'is_active': True,
            'cloud_account': False,
        })
        return super().create_user(rs, data)

    @access("anonymous")
    @REQUESTdata(("secret", "str"), ("username", "email"))
    def genesis_form(self, rs, case_id, secret, username):
        """Render form."""
        return super().genesis_form(rs, case_id, secret, username)

    @access("anonymous", {"POST"})
    @REQUESTdata(("secret", "str"))
    @REQUESTdatadict(
        "title", "given_names", "family_name", "name_supplement",
        "display_name", "birthday", "gender", "telephone", "mobile",
        "address", "address_supplement", "postal_code", "location",
        "country", "username")
    def genesis(self, rs, case_id, secret, data):
        """Create new user account."""
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
        params = {'result': result, 'query': query}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data)
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
        data = check(rs, "past_event_data", data, initialization=True)
        if rs.errors:
            return self.create_past_event_form(rs)
        new_id = self.eventproxy.create_past_event(rs, data)
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
        data = check(rs, "past_course_data", data, initialization=True)
        if rs.errors:
            return self.create_past_course_form(rs, event_id)
        new_id = self.eventproxy.create_past_course(rs, data)
        return self.redirect(rs, "event/show_past_course",
                             {'course_id': new_id})

    @access("event_admin", {"POST"})
    def delete_past_course(self, rs, event_id, course_id):
        """Delete a concluded course."""
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
        locked = (event_data['offline_lock']
                  != self.conf.CDEDB_OFFLINE_DEPLOYMENT)
        return self.render(rs, "show_event", {
            'event_data': event_data, 'course_data': course_data,
            'locked': locked})

    @access("event_user")
    @event_guard()
    def change_event_form(self, rs, event_id):
        """Render form."""
        data = self.eventproxy.get_event_data_one(rs, event_id)
        merge_dicts(rs.values, data)
        orgas = self.eventproxy.acquire_data(rs, data['orgas'])
        locked = (data['offline_lock'] != self.conf.CDEDB_OFFLINE_DEPLOYMENT)
        minor_form_present = os.path.isfile(os.path.join(
            self.conf.STORAGE_DIR, 'minor_form', str(event_id)))
        return self.render(rs, "change_event", {
            'data': data, 'orgas': orgas, 'locked': locked,
            'minor_form_present': minor_form_present})

    @access("event_user", {"POST"})
    @REQUESTdatadict(
        "title", "organizer", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "use_questionnaire", "notes")
    @event_guard(check_offline=True)
    def change_event(self, rs, event_id, data):
        """Modify an event organized via DB."""
        data['id'] = event_id
        data = check(rs, "event_data", data)
        if rs.errors:
            return self.change_event_form(rs, event_id)
        num = self.eventproxy.set_event_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

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
            return self.change_event_form(rs, event_id)
        blob = minor_form.read()
        path = os.path.join(self.conf.STORAGE_DIR, 'minor_form', str(event_id))
        with open(path, 'wb') as f:
            f.write(blob)
        rs.notify("success", "Form updated.")
        return self.redirect(rs, "event/change_event")

    @access("event_user", {"POST"})
    @REQUESTdata(("orga_id", "cdedbid"))
    @event_guard(check_offline=True)
    def add_orga(self, rs, event_id, orga_id):
        """Make an additional persona become orga."""
        if rs.errors:
            return self.change_event_form(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] | {orga_id}
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

    @access("event_user", {"POST"})
    @REQUESTdata(("orga_id", "int"))
    @event_guard(check_offline=True)
    def remove_orga(self, rs, event_id, orga_id):
        """Demote a persona.

        This can drop your own orga role.
        """
        if rs.errors:
            return self.change_event_form(rs, event_id)
        data = self.eventproxy.get_event_data_one(rs, event_id)
        newdata = {
            'id': event_id,
            'orgas': data['orgas'] - {orga_id}
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

    @access("event_user")
    @event_guard()
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
        return self.redirect(rs, "event/change_event")

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
            return self.change_event_form(rs, event_id)
        newdata = {
            'id': event_id,
            'parts': {
                -1: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

    @access("event_user")
    @event_guard()
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
        ## field_name is fixed
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        data['field_name'] = event_data['fields'][field_id]['field_name']
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
        return self.redirect(rs, "event/change_event")

    @access("event_user", {"POST"})
    @REQUESTdatadict("field_name", "kind", "entries")
    @event_guard(check_offline=True)
    def add_field(self, rs, event_id, data):
        """Create a new field to attach information to a registration."""
        data = check(rs, "event_field_data", data)
        if rs.errors:
            return self.change_event_form(rs, event_id)
        newdata = {
            'id': event_id,
            'fields': {
                -1: data
            }
        }
        num = self.eventproxy.set_event_data(rs, newdata)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

    @access("event_user", {"POST"})
    @REQUESTdata(("field_id", "int"))
    @event_guard(check_offline=True)
    def remove_field(self, rs, event_id, field_id):
        """Delete a field.

        This does not delete the associated information allready
        submitted, but makes it inaccessible.
        """
        if rs.errors:
            return self.change_event_form(rs, event_id)
        data = {
            'id': event_id,
            'fields': {
                field_id: None
            }
        }
        num = self.eventproxy.set_event_data(rs, data)
        self.notify_integer_success(rs, num)
        return self.redirect(rs, "event/change_event")

    @access("event_admin")
    def create_event_form(self, rs):
        """Render form."""
        return self.render(rs, "create_event")

    @access("event_admin", {"POST"})
    @REQUESTdatadict(
        "title", "organizer", "description", "shortname",
        "registration_start", "registration_soft_limit",
        "registration_hard_limit", "use_questionnaire", "notes",
        "orga_ids")
    def create_event(self, rs, data):
        """Create a new event organized via DB."""
        if data['orga_ids'] is not None:
            data['orgas'] = {check(rs, "cdedbid", x.strip(), "orga_ids")
                             for x in data['orga_ids'].split(",")}
        del data['orga_ids']
        data = check(rs, "event_data", data, initialization=True)
        if rs.errors:
            return self.create_event_form(rs)
        new_id = self.eventproxy.create_event(rs, data)
        rs.notify("success", "Event created.")
        return self.redirect(rs, "event/show_event", {"event_id": new_id})

    @access("event_user")
    def show_course(self, rs, event_id, course_id):
        """Display course associated to event organized via DB."""
        event_data = self.eventproxy.get_event_data_one(rs, event_id)
        course_data = self.eventproxy.get_course_data_one(rs, course_id)
        return self.render(rs, "show_course", {
            'event_data': event_data, 'course_data': course_data})

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
        data = check(rs, "course_data", data, initialization=True)
        if rs.errors:
            return self.create_course_form(rs, event_id)
        new_id = self.eventproxy.create_course(rs, data)
        rs.notify("success", "Course created.")
        return self.redirect(rs, "event/show_course", {'course_id': new_id})
