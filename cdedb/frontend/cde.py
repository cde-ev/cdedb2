#!/usr/bin/env python3

"""Services for the cde realm."""

import logging
from cdedb.frontend.common import REQUESTdata, \
    REQUESTdatadict, access_decorator_generator, ProxyShim, \
    encodedparam_decorator_generator, connect_proxy
from cdedb.frontend.common import check_validation as check
from cdedb.frontend.uncommon import AbstractUserFrontend
import cdedb.database.constants as const

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))
encodedparam = encodedparam_decorator_generator("cde")

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
    @REQUESTdata("confirm_id")
    @encodedparam("confirm_id")
    def show_user(self, rs, persona_id, confirm_id=None):
        confirm_id = check(rs, "int", confirm_id, "confirm_id")
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/error")
        realm = self.coreproxy.get_realm(rs, persona_id)
        red = self.redirect_realm(
            rs, persona_id, "show_user", params={
                'confirm_id' : self.encode_parameter(
                    "{}/show_user".format(realm), "confirm_id", confirm_id)})
        if red:
            return red
        data = self.cdeproxy.get_data_single(rs, persona_id)
        participation_info = self.eventproxy.participation_info(rs, persona_id)
        return self.render(rs, "show_user", {
            'data' : data, 'participation_info' : participation_info})

    @access("user")
    def change_user_form(self, rs, persona_id):
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        if self.redirect_realm(rs, persona_id, "change_user_form"):
            return self.redirect_realm(rs, persona_id, "change_user_form")
        generation = self.cdeproxy.get_generation(rs, persona_id)
        data = self.cdeproxy.get_data_single(rs, persona_id)
        rs.values.update(data)
        rs.values['generation'] = generation
        return self.render(rs, "change_user")

    @access("user", {"POST"})
    @REQUESTdata("generation")
    @REQUESTdatadict("display_name", "family_name", "given_names", "title",
                     "name_supplement", "telephone", "mobile",
                     "address_supplement", "address", "postal_code",
                     "location", "country", "address_supplement2", "address2",
                     "postal_code2", "location2", "country2", "weblink",
                     "specialisation", "affiliation", "timeline", "interests",
                     "free_form", "bub_search")
    def change_user(self, rs, persona_id, data=None, generation=None):
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        if self.redirect_realm(rs, persona_id, "change_user_form"):
            return self.redirect_realm(rs, persona_id, "change_user_form")
        data = data or {}
        data['id'] = persona_id
        data = check(rs, "member_data", data)
        generation = check(rs, "int", generation, "generation")
        if rs.errors:
            return self.render(rs, "change_user")
        num = self.cdeproxy.change_user(rs, data, generation)
        if num > 0:
            rs.notify("success", "Change committed.")
        elif num < 0:
            rs.notify("info", "Change pending.")
        else:
            rs.notify("warning", "Change failed.")
        return self.redirect(rs, "cde/show_user", params={
            'confirm_id' : self.encode_parameter("cde/show_user", "confirm_id",
                                                 persona_id)})

    @access("persona", {'POST'})
    @REQUESTdata('new_username', 'password')
    @encodedparam('new_username')
    def do_username_change(self, rs, persona_id, new_username="",
                           password=""):
        """Now we can do the actual change. This is in the cde frontend to
        allow the changelog functionality. (Otherwise this would be in the
        core frontend.)"""
        if persona_id != rs.user.persona_id and not self.is_admin(rs):
            return werkzeug.exceptions.Forbidden()
        new_username = check(rs, 'email', new_username, "new_username")
        password = check(rs, 'str', password, "password")
        ## do not leak the password
        rs.values['password'] = ""
        if rs.errors:
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

    @access("cde_admin")
    def list_pending_changes(self, rs):
        """List non-committed changelog entries."""
        pending = self.cdeproxy.get_pending_changes(rs)
        return self.render(rs, "list_pending_changes", {'pending' : pending})

    @access("cde_admin")
    def inspect_change(self, rs, persona_id):
        """Look at a pending change"""
        history = self.cdeproxy.get_history(rs, persona_id, generations=None)
        pending = history[max(history)]
        if pending['change_status'] != const.MEMBER_CHANGE_PENDING:
            rs.notify("warning", "Persona has no pending change.")
            return self.redirect(rs, "cde/list_pending_changes")
        current = history[max(
            key for key in history
            if history[key]['change_status'] == const.MEMBER_CHANGE_COMMITTED)]
        diff = {key for key in pending if current[key] != pending[key]}
        return self.render(rs, "inspect_change", {
            'pending' : pending, 'current' : current, 'diff' : diff})

    @access("cde_admin", {"POST"})
    @REQUESTdata("generation", "ack")
    def resolve_change(self, rs, persona_id, generation="", ack=""):
        generation = check(rs, 'int', generation, "generation")
        ack = check(rs, 'bool', ack, "ack")
        if rs.errors:
            return self.redirect(rs, "cde/list_pending_changes")
        self.cdeproxy.resolve_change(rs, persona_id, generation, ack)
        if ack:
            rs.notify("success", "Change comitted.")
        else:
            rs.notify("info", "Change dropped.")
        return self.redirect(rs, "cde/list_pending_changes")
