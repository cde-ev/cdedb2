#!/usr/bin/env python3

"""Services for the cde realm."""

import logging
import os.path
import hashlib

import cdedb.database.constants as const
from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access_decorator_generator,
    ProxyShim, connect_proxy, persona_dataset_guard, check_validation as check)
from cdedb.frontend.uncommon import AbstractUserFrontend

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))

class CdeFrontend(AbstractUserFrontend):
    """This offers services to the members as well as facilities for managing
    the organization."""
    realm = "cde"
    logger = logging.getLogger(__name__)
    user_management = {
        "proxy" : lambda obj: obj.cdeproxy,
        "validator" : "member_data",
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
        return self.render(rs, "index")

    @access("user")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        if self.coreproxy.get_realm(rs, persona_id) != self.realm:
            return werkzeug.exceptions.NotFound()
        data = self.cdeproxy.get_data_single(rs, persona_id)
        participation_info = self.eventproxy.participation_info(rs, persona_id)
        foto = self.cdeproxy.get_foto(rs, persona_id)
        return self.render(rs, "show_user", {
            'data' : data, 'participation_info' : participation_info,
            'foto' : foto})

    @access("user")
    @persona_dataset_guard()
    def change_user_form(self, rs, persona_id):
        generation = self.cdeproxy.get_generation(rs, persona_id)
        data = self.cdeproxy.get_data_single(rs, persona_id)
        rs.values.update(data)
        rs.values['generation'] = generation
        return self.render(rs, "change_user")

    @access("user", {"POST"})
    @REQUESTdata(("generation", "int"))
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code",
                     "location", "country", "address_supplement2", "address2",
                     "postal_code2", "location2", "country2", "weblink",
                     "specialisation", "affiliation", "timeline", "interests",
                     "free_form", "bub_search")
    @persona_dataset_guard()
    def change_user(self, rs, persona_id, generation, data):
        data['id'] = persona_id
        data = check(rs, "member_data", data)
        if rs.errors:
            return self.render(rs, "change_user")
        num = self.cdeproxy.change_user(rs, data, generation)
        if num > 0:
            rs.notify("success", "Change committed.")
        elif num < 0:
            rs.notify("info", "Change pending.")
        else:
            rs.notify("warning", "Change failed.")
        return self.redirect_show_user(rs, persona_id)

    @access("persona", {'POST'})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    @persona_dataset_guard(realms=None)
    def do_username_change(self, rs, persona_id, new_username, password):
        """Now we can do the actual change. This is in the cde frontend to
        allow the changelog functionality. (Otherwise this would be in the
        core frontend.)"""
        ## do not leak the password
        rs.values['password'] = ""
        if rs.errors:
            rs.notify("error", "Failed.")
            return self.redirect(rs, "core/change_username_form")
        token = self.coreproxy.change_username_token(
            rs, persona_id, new_username, password)
        success, message = self.cdeproxy.change_username(
            rs, persona_id, new_username, token)
        if not success:
            rs.notify("error", message)
            return self.redirect(rs, "core/username_change_form")
        else:
            rs.notify("success", "Username changed.")
            return self.redirect(rs, "core/index")

    @access("cde_admin", {'POST'})
    @REQUESTdata(('new_username', 'email'))
    def admin_username_change(self, rs, persona_id, new_username):
        """This is in the cde frontend to allow the changelog
        functionality. (Otherwise this would be in the core frontend.)"""
        if rs.errors:
            rs.notify("error", "Failed.")
            return self.redirect(rs, "core/admin_username_change_form")
        token = self.coreproxy.change_username_token(
            rs, persona_id, new_username, "dummy")
        success, message = self.cdeproxy.change_username(
            rs, persona_id, new_username, token)
        if not success:
            rs.notify("error", message)
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            rs.notify("success", "Username changed.")
            return self.redirect(rs, "core/show_user")

    @access("cde_admin")
    def list_pending_changes(self, rs):
        """List non-committed changelog entries."""
        pending = self.cdeproxy.get_pending_changes(rs)
        return self.render(rs, "list_pending_changes", {'pending' : pending})

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
            if history[key]['change_status'] == const.MemberChangeStati.committed)]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending' : pending, 'current' : current, 'diff' : diff})

    @access("cde_admin", {"POST"})
    @REQUESTdata(("generation", "int"), ("ack", "bool"))
    def resolve_change(self, rs, persona_id, generation, ack):
        if rs.errors:
            rs.notify("error", "Failed.")
            return self.list_pending_changes(rs)
        self.cdeproxy.resolve_change(rs, persona_id, generation, ack)
        if ack:
            rs.notify("success", "Change comitted.")
        else:
            rs.notify("info", "Change dropped.")
        return self.redirect(rs, "cde/list_pending_changes")

    @access("user")
    def get_foto(self, rs, foto):
        """Retrieve profile picture"""
        path = os.path.join(self.conf.STORAGE_DIR, "foto", foto)
        return self.send_file(rs, path)

    @access("user")
    @persona_dataset_guard()
    def set_foto_form(self, rs, persona_id):
        """Render form."""
        data = self.cdeproxy.get_data_single(rs, persona_id)
        return self.render(rs, "set_foto", {'data' : data})

    @access("user", {"POST"})
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
        self.cdeproxy.set_foto(rs, persona_id, myhash.hexdigest())
        if previous:
            if not self.cdeproxy.foto_usage(rs, myhash.hexdigest()):
                path = os.path.join(self.conf.STORAGE_DIR, 'foto', previous)
                os.remove(path)
        rs.notify("success", "Foto updated.")
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def consent_decision_form(self, rs):
        """After login ask cde members for decision about searchability. Do
        this only if no decision has been made in the past.
        """
        if rs.user.realm != "cde" or rs.user.is_searchable:
            return self.redirect(rs, "core/index")
        data = self.cdeproxy.get_data_single(rs, rs.user.persona_id)
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        return self.render(rs, "consent_decision", {'data' : data})

    @access("member", {"POST"})
    @REQUESTdata(("ack", "bool"))
    def consent_decision(self, rs, ack):
        """Record decision."""
        data = self.cdeproxy.get_data_single(rs, rs.user.persona_id)
        if rs.errors:
            rs.notify("error", "Failed.")
            return self.render(rs, "consent_decision", {'data' : data})
        if data['decided_search']:
            return self.redirect(rs, "core/index")
        if ack:
            status = const.PersonaStati.search_member.value
        else:
            status = const.PersonaStati.member.value
        new_data = {
            'id' : rs.user.persona_id,
            'decided_search' : True,
            'status' : status
        }
        num = self.cdeproxy.change_user(rs, new_data, None, may_wait=False)
        if num != 1:
            rs.notify("error", "Failed.")
            return self.render(rs, "consent_decision", {'data' : data})
        if ack:
            rs.notify("success", "Consent noted.")
        else:
            rs.notify("info", "Decision noted.")
        return self.redirect(rs, "core/index")
