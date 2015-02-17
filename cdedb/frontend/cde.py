#!/usr/bin/env python3

"""Services for the cde realm."""

import logging
import os.path
import hashlib
import werkzeug

import cdedb.database.constants as const
from cdedb.common import merge_dicts, name_key
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access, ProxyShim,
    connect_proxy, persona_dataset_guard, check_validation as check)
from cdedb.frontend.uncommon import AbstractUserFrontend
from cdedb.query import QUERY_SPECS, mangle_query_input, QueryOperators

class CdEFrontend(AbstractUserFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy": lambda obj: obj.cdeproxy,
        "validator": "member_data",
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.cdeproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("cde")))
        self.eventproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("event")))

    def finalize_session(self, rs, sessiondata):
        return super().finalize_session(rs, sessiondata)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def index(self, rs):
        """Render start page."""
        return self.render(rs, "index")

    @access("formermember")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        if self.coreproxy.get_realm(rs, persona_id) != self.realm:
            return werkzeug.exceptions.NotFound("No such user in this realm.")
        data = self.cdeproxy.get_data_one(rs, persona_id)
        participation_info = self.eventproxy.participation_info(rs, persona_id)
        foto = self.cdeproxy.get_foto(rs, persona_id)
        data['is_member'] = data['status'] in const.MEMBER_STATI
        data['is_searchable'] = data['status'] in const.SEARCHMEMBER_STATI
        data['db_privileges_ascii'] = ", ".join(
            bit.name for bit in const.PrivilegeBits
            if data['db_privileges'] & bit.value)
        params = {
            'data': data,
            'participation_info': participation_info,
            'foto': foto,
        }
        if data['status'] == const.PersonaStati.archived_member:
            if self.is_admin(rs):
                return self.render(rs, "show_archived_user", params)
            else:
                rs.notify("error", "Accessing archived member impossible.")
                return self.redirect(rs, "core/index")
        else:
            return self.render(rs, "show_user", params)

    @access("formermember")
    def change_user_form(self, rs):
        data = self.cdeproxy.get_data_one(rs, rs.user.persona_id)
        data['generation'] = self.cdeproxy.get_generation(rs,
                                                          rs.user.persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_user", {'username': data['username']})

    @access("formermember", {"POST"})
    @REQUESTdata(("generation", "int"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "bub_search")
    def change_user(self, rs, generation, data):
        data['id'] = rs.user.persona_id
        data = check(rs, "member_data", data)
        if rs.errors:
            return self.change_user_form(rs)
        change_note = "Normal dataset change."
        code = self.cdeproxy.change_user(rs, data, generation,
                                         change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("cde_admin")
    @persona_dataset_guard()
    def admin_change_user_form(self, rs, persona_id):
        data = self.cdeproxy.get_data_one(rs, persona_id)
        data['generation'] = self.cdeproxy.get_generation(rs, persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "admin_change_user",
                           {'username': data['username']})

    @access("cde_admin", {"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    @REQUESTdatadict(
        "title", "given_names", "family_name", "birth_name", "name_supplement",
        "display_name", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "gender", "birthday", "telephone",
        "mobile", "weblink", "address", "address_supplement", "postal_code",
        "location", "country", "address2", "address_supplement2",
        "postal_code2", "location2", "country2", "bub_search",
        "cloud_account", "notes")
    @persona_dataset_guard()
    def admin_change_user(self, rs, persona_id, generation, change_note, data):
        data['id'] = persona_id
        data = check(rs, "member_data", data)
        if change_note is None:
            change_note = "Admin dataset change."
        if rs.errors:
            return self.admin_change_user_form(rs, persona_id)
        code = self.cdeproxy.change_user(rs, data, generation,
                                         change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def list_pending_changes(self, rs):
        """List non-committed changelog entries."""
        pending = self.cdeproxy.get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @access("cde_admin")
    def inspect_change(self, rs, persona_id):
        """Look at a pending change."""
        history = self.cdeproxy.get_history(rs, persona_id, generations=None)
        pending = history[max(history)]
        if pending['change_status'] != const.MemberChangeStati.pending:
            rs.notify("warning", "Persona has no pending change.")
            return self.list_pending_changes(rs)
        current = history[max(
            key for key in history
            if (history[key]['change_status']
                == const.MemberChangeStati.committed))]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending': pending, 'current': current, 'diff': diff})

    @access("cde_admin", {"POST"})
    @REQUESTdata(("generation", "int"), ("ack", "bool"))
    def resolve_change(self, rs, persona_id, generation, ack):
        """Make decision."""
        if rs.errors:
            return self.list_pending_changes(rs)
        code = self.cdeproxy.resolve_change(rs, persona_id, generation, ack)
        message = "Change comitted." if ack else "Change dropped."
        self.notify_return_code(rs, code, success=message)
        return self.redirect(rs, "cde/list_pending_changes")

    @access("formermember")
    def get_foto(self, rs, foto):
        """Retrieve profile picture."""
        path = os.path.join(self.conf.STORAGE_DIR, "foto", foto)
        return self.send_file(rs, path=path)

    @access("formermember")
    @persona_dataset_guard()
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        data = self.cdeproxy.get_data_one(rs, persona_id)
        return self.render(rs, "set_foto", {'data': data})

    @access("formermember", {"POST"})
    @REQUESTfile("foto")
    @persona_dataset_guard()
    def set_foto(self, rs, persona_id, foto):
        """Set profile picture."""
        foto = check(rs, 'profilepic', foto, "foto")
        if rs.errors:
            return self.set_foto_form(rs, persona_id)
        previous = self.cdeproxy.get_foto(rs, persona_id)
        blob = foto.read()
        myhash = hashlib.sha512()
        myhash.update(blob)
        path = os.path.join(self.conf.STORAGE_DIR, 'foto', myhash.hexdigest())
        if not os.path.isfile(path):
            with open(path, 'wb') as f:
                f.write(blob)
        code = self.cdeproxy.set_foto(rs, persona_id, myhash.hexdigest())
        if previous:
            if not self.cdeproxy.foto_usage(rs, myhash.hexdigest()):
                path = os.path.join(self.conf.STORAGE_DIR, 'foto', previous)
                os.remove(path)
        self.notify_return_code(rs, code, success="Foto updated.")
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def consent_decision_form(self, rs):
        """After login ask cde members for decision about searchability. Do
        this only if no decision has been made in the past.

        This is the default page after login, but most users will instantly
        be redirected.
        """
        if rs.user.realm != "cde" or rs.user.is_searchable:
            return self.redirect(rs, "core/index")
        data = self.cdeproxy.get_data_one(rs, rs.user.persona_id)
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        return self.render(rs, "consent_decision", {'data': data})

    @access("member", {"POST"})
    @REQUESTdata(("ack", "bool"))
    def consent_decision(self, rs, ack):
        """Record decision."""
        if rs.errors:
            return self.consent_decision_form(rs)
        data = self.cdeproxy.get_data_one(rs, rs.user.persona_id)
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        if ack:
            status = const.PersonaStati.searchmember.value
        else:
            status = const.PersonaStati.member.value
        new_data = {
            'id': rs.user.persona_id,
            'decided_search': True,
            'status': status
        }
        change_note = "Consent decision (is {}).".format(ack)
        code = self.cdeproxy.change_user(rs, new_data, None, may_wait=False,
                                         change_note=change_note)
        message = "Consent noted." if ack else "Decision noted."
        self.notify_return_code(rs, code, success=message)
        if not code:
            return self.consent_decision_form(rs)
        return self.redirect(rs, "core/index")

    @access("searchmember")
    @REQUESTdata(("submitform", "bool"))
    def member_search(self, rs, submitform):
        """Render form and do search queries. This has a double meaning so
        that we are able to update the course selection upon request.

        ``submitform`` is present in the request data if the corresponding
        button was pressed and absent otherwise.
        """
        spec = QUERY_SPECS['qview_cde_member']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=not submitform)
        if not submitform or rs.errors:
            events = {k: v for k, v in self.eventproxy.list_events(
                rs, past=True).items()}
            event_id = None
            if query:
                for field, _, value in query.constraints:
                    if field == "event_id" and value:
                        event_id = value
            courses = tuple()
            if event_id:
                courses = {k: v for k, v in self.eventproxy.list_courses(
                    rs, event_id, past=True).items()}
            choices = {"event_id": events, 'course_id': courses}
            return self.render(rs, "member_search",
                               {'spec': spec, 'choices': choices,
                                'queryops': QueryOperators,})
        else:
            query.scope = "qview_cde_member"
            query.fields_of_interest.append('member_data.persona_id')
            result = self.cdeproxy.submit_general_query(rs, query)
            result = sorted(result, key=name_key)
            if len(result) == 1:
                return self.redirect_show_user(rs, result[0]['persona_id'])
            if (len(result) > self.conf.MAX_QUERY_RESULTS
                    and not self.is_admin(rs)):
                result = result[:self.conf.MAX_QUERY_RESULTS]
                rs.notify("info", "Too many query results.")
            return self.render(rs, "member_search_result", {'result': result})

    @access("cde_admin")
    def user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_cde_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        events = self.eventproxy.list_events(rs, past=True)
        choices = {'event_id': events,
                   'status': self.enum_choice(rs, const.PersonaStati),
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_cde_user']
        return self.render(rs, "user_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries,})

    @access("cde_admin")
    @REQUESTdata(("CSV", "bool"))
    def user_search(self, rs, CSV):
        """Perform search."""
        spec = QUERY_SPECS['qview_cde_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.user_search_form(rs)
        query.scope = "qview_cde_user"
        result = self.cdeproxy.submit_general_query(rs, query)
        choices = {'status': self.enum_choice(rs, const.PersonaStati),
                   'gender': self.enum_choice(rs, const.Genders)}
        params = {'result': result, 'query': query, 'choices': choices}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            return self.render(rs, "user_search_result", params)

    @access("cde_admin")
    def archived_user_search_form(self, rs):
        """Render form."""
        spec = QUERY_SPECS['qview_cde_archived_user']
        ## mangle the input, so we can prefill the form
        mangle_query_input(rs, spec)
        events = self.eventproxy.list_events(rs, past=True)
        choices = {'event_id': events,
                   'status': self.enum_choice(rs, const.PersonaStati),
                   'gender': self.enum_choice(rs, const.Genders)}
        default_queries = self.conf.DEFAULT_QUERIES['qview_cde_archived_user']
        return self.render(rs, "archived_user_search", {
            'spec': spec, 'choices': choices, 'queryops': QueryOperators,
            'default_queries': default_queries,})

    @access("cde_admin")
    @REQUESTdata(("CSV", "bool"))
    def archived_user_search(self, rs, CSV):
        """Perform search.

        Archived users are somewhat special since they are not visible
        otherwise.
        """
        spec = QUERY_SPECS['qview_cde_archived_user']
        query = check(rs, "query_input", mangle_query_input(rs, spec), "query",
                      spec=spec, allow_empty=False)
        if rs.errors:
            return self.archived_user_search_form(rs)
        query.scope = "qview_cde_archived_user"
        result = self.cdeproxy.submit_general_query(rs, query)
        choices = {'status': self.enum_choice(rs, const.PersonaStati),
                   'gender': self.enum_choice(rs, const.Genders)}
        params = {'result': result, 'query': query, 'choices': choices}
        if CSV:
            data = self.fill_template(rs, 'web', 'csv_search_result', params)
            return self.send_file(rs, data=data,
                                  filename=self.i18n("result.txt", rs.lang))
        else:
            return self.render(rs, "archived_user_search_result", params)

    @access("cde_admin")
    @persona_dataset_guard()
    def modify_membership_form(self, rs, persona_id):
        """Render form."""
        data = self.cdeproxy.get_data_one(rs, persona_id)
        data['is_member'] = data['status'] in const.MEMBER_STATI
        data['is_searchable'] = data['status'] in const.SEARCHMEMBER_STATI
        return self.render(rs, "modify_membership", {
            'data': data, 'stati': const.PersonaStati})

    @access("cde_admin", {"POST"})
    @persona_dataset_guard()
    @REQUESTdata(("newstatus", "persona_status"))
    def modify_membership(self, rs, persona_id, newstatus):
        """Change association status."""
        if newstatus not in const.ALL_CDE_STATI:
            rs.errors.append(("newstatus", ValueError("Wrong realm.")))
        if rs.errors:
            return self.modify_membership_form(rs, persona_id)
        data = {
            'id': persona_id,
            'status': newstatus,
        }
        if newstatus == const.PersonaStati.formermember:
            data['decided_search'] = False
        elif newstatus == const.PersonaStati.archived_member:
            raise NotImplementedError("TODO")
        change_note = "Membership change to {}".format(newstatus.name)
        code = self.cdeproxy.change_user(rs, data, None, may_wait=False,
                                         change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("cde_admin")
    def create_user_form(self, rs):
        defaults = {
            'status': const.PersonaStati.member.value,
            'bub_search': False,
            'cloud_account': True,
        }
        merge_dicts(rs.values, defaults)
        return super().create_user_form(rs)

    @access("cde_admin", {"POST"})
    @REQUESTdatadict(
        "title", "given_names", "family_name", "birth_name", "name_supplement",
        "display_name", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "gender", "birthday", "username",
        "telephone", "mobile", "weblink", "address", "address_supplement",
        "postal_code", "location", "country", "address2",
        "address_supplement2", "postal_code2", "location2", "country2",
        "status", "trial_member", "bub_search", "cloud_account", "notes")
    def create_user(self, rs, data):
        data['is_active'] = True
        return super().create_user(rs, data)

    def genesis_form(self, rs, case_id, secret):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available in cde realm.")

    def genesis(self, rs, case_id, secret, data):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available in cde realm.")
