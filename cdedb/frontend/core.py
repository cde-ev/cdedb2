#!/usr/bin/env python3

"""Services for the core realm."""

import datetime
import logging
import pytz
import werkzeug
from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, access, ProxyShim, basic_redirect,
    connect_proxy, check_validation as check, persona_dataset_guard)
import cdedb.database.constants as const

class CoreFrontend(AbstractFrontend):
    """Note that there is no user role since the basic distinction is between
    anonymous access and personas. """
    realm = "core"
    logger = logging.getLogger(__name__)

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        self.coreproxy = ProxyShim(connect_proxy(
            self.conf.SERVER_NAME_TEMPLATE.format("core")))

    def finalize_session(self, rs, sessiondata):
        return super().finalize_session(rs, sessiondata)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("anonymous")
    @REQUESTdata(("wants", "#str_or_None"))
    def index(self, rs, wants=None):
        """Basic entry point.

        :param wants: URL to redirect to upon login
        """
        if wants:
            rs.values['wants'] = self.encode_parameter("core/login", "wants",
                                                       wants)
        return self.render(rs, "index")

    @access("anonymous")
    @REQUESTdata(("kind", "printable_ascii"))
    def error(self, rs, kind):
        """Fault page.

        This may happen upon a database serialization failure during
        concurrent accesses.
        """
        if kind not in {"general", "database"}:
            kind = "general"
        return self.render(rs, "error", {
            'kind' : kind, 'now' : datetime.datetime.now(pytz.utc)})

    @access("anonymous", {"POST"})
    @REQUESTdata(("username", "printable_ascii"), ("password", "str"),
                 ("wants", "#str_or_None"))
    def login(self, rs, username, password, wants):
        """Create session.

        :param wants: URL to redirect to
        """
        if rs.errors:
            return self.index(rs)
        sessionkey = self.coreproxy.login(rs, username, password,
                                          rs.request.remote_addr)
        if not sessionkey:
            rs.notify("error", "Login failure.")
            rs.errors.extend((("username", ValueError()),
                              ("password", ValueError())))
            return self.index(rs)
        if wants:
            basic_redirect(rs, wants)
        else:
            self.redirect(rs, "cde/consent_decision_form")
        rs.response.set_cookie("sessionkey", sessionkey)
        return rs.response

    @access("persona", {"POST"})
    def logout(self, rs):
        """Invalidate session."""
        self.coreproxy.logout(rs)
        self.redirect(rs, "core/index")
        rs.response.delete_cookie("sessionkey")
        return rs.response

    @access("persona")
    def mydata(self, rs):
        """Convenience entry point for own data."""
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("persona")
    @REQUESTdata(("confirm_id", "#int"))
    def show_user(self, rs, persona_id, confirm_id):
        """Common entry point redirecting to user's realm."""
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        realm = self.coreproxy.get_realm(rs, persona_id)
        params = {'confirm_id' : self.encode_parameter(
            "{}/show_user".format(realm), "confirm_id", confirm_id)}
        return self.redirect(
            rs, "{}/show_user".format(realm), params=params)

    @access("core_admin")
    @REQUESTdata(("id_to_show", "int"))
    def admin_show_user(self, rs, id_to_show):
        """Allow admins to view any user data set."""
        if rs.errors:
            return self.redirect(rs, "core/index")
        return self.redirect_show_user(rs, id_to_show)

    @access("persona")
    def change_user_form(self, rs, persona_id):
        """Common entry point redirecting to user's realm."""
        realm = self.coreproxy.get_realm(rs, persona_id)
        return self.redirect(rs, "{}/change_user_form".format(realm))

    @access("persona")
    def change_password_form(self, rs):
        """Render form."""
        return self.render(rs, "change_password")

    @access("persona", {"POST"})
    @REQUESTdata(("old_password", "str"), ("new_password", "str"),
                 ("new_password2", "str"))
    def change_password(self, rs, old_password, new_password, new_password2):
        """Update your own password."""
        if new_password != new_password2:
            rs.errors.append(("new_password", ValueError("No match.")))
            rs.errors.append(("new_password2", ValueError("No match.")))
        new_password = check(rs, "password_strength", new_password,
                             "new_password")
        if rs.errors:
            return self.change_password_form(rs)
        success, message = self.coreproxy.change_password(
            rs, rs.user.persona_id, old_password, new_password)
        if not success:
            rs.errors.append(("old_password", ValueError("Wrong password.")))
            rs.notify("error", message)
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
            return self.change_password_form(rs)
        else:
            rs.notify("success", "Password changed.")
            return self.redirect(rs, "core/index")

    @access("anonymous")
    def reset_password_form(self, rs):
        """Render form."""
        return self.render(rs, "reset_password")

    @access("anonymous")
    @REQUESTdata(("email", "email"))
    def send_password_reset_link(self, rs, email):
        """First send a confirmation mail, to prevent an adversary from
        changing random passwords."""
        if rs.errors:
            return self.reset_password_form(rs)
        exists = self.coreproxy.verify_existence(rs, email)
        if not exists:
            rs.errors.append(("email", ValueError("Nonexistant user.")))
            return self.reset_password_form(r)
        self.do_mail(
            rs, "reset_password",
            {'To' : (email,), 'Subject' : 'CdEDB password reset'},
            {'email' : self.encode_parameter(
                "core/do_password_reset_form", "email", email)})
        self.logger.info("Sent password reset mail to {} for IP {}.".format(
            email, rs.request.remote_addr))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("email", "#email"))
    def do_password_reset_form(self, rs, email):
        """Second form. Pretty similar to first form, but now we know, that
        the account owner actually wants the reset."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email)
        return self.render(rs, "do_password_reset")

    @access("anonymous", {"POST"})
    @REQUESTdata(("email", "#email"))
    def do_password_reset(self, rs, email):
        """Now we can send an email with a new password."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        success, message = self.coreproxy.reset_password(rs, email)
        if not success:
            rs.notify("error", message)
            return self.redirect(rs, "core/reset_password_form")
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To' : (email,),
                          'Subject' : 'CdEDB password reset successful'},
                         {'password' : message})
            rs.notify("success", "Password reset.")
            return self.redirect(rs, "core/index")

    @access("core_admin", {"POST"})
    def admin_password_reset(self, rs, persona_id):
        """Administrative password reset."""
        data = self.coreproxy.get_data_single(rs, persona_id)
        success, message = self.coreproxy.reset_password(rs, data['username'])
        if not success:
            rs.notify("error", message)
            return self.redirect_show_user(rs, persona_id)
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To' : (data['username'],),
                          'Subject' : 'CdEDB password reset successful'},
                         {'password' : message})
            rs.notify("success", "Password reset.")
            return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_username_form(self, rs):
        """Render form."""
        return self.render(rs, "change_username")

    @access("persona")
    @REQUESTdata(("new_username", "email"))
    def send_username_change_link(self, rs, new_username):
        """Verify new name with test email."""
        if rs.errors:
            return self.change_username_form(rs)
        self.do_mail(rs, "change_username",
                     {'To' : (new_username,),
                      'Subject' : 'CdEDB username change'},
                     {'new_username' : self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username)})
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata(("new_username", "#email"))
    @persona_dataset_guard(realms=None)
    def do_username_change_form(self, rs, persona_id, new_username):
        """Email is now verified or we are admin."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/change_username_form")
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username)
        return self.render(rs, "do_username_change")

    @access("persona", {'POST'})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    @persona_dataset_guard(realms=None)
    def do_username_change(self, rs, persona_id, new_username, password):
        """Now we can do the actual change."""
        if rs.errors:
            rs.notify("error", "Link expired")
            return self.redirect(rs, "core/change_username_form")
        success, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password)
        if not success:
            rs.notify("error", message)
            return self.redirect(rs, "core/username_change_form")
        else:
            rs.notify("success", "Username changed.")
            return self.redirect(rs, "core/index")

    @access("core_admin")
    def admin_username_change_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_data_single(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data' : data})

    @access("core_admin", {'POST'})
    @REQUESTdata(('new_username', 'email'))
    def admin_username_change(self, rs, persona_id, new_username):
        """Change username without verification."""
        if rs.errors:
            return self.redirect(rs, "core/admin_username_change_form")
        success, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        if not success:
            rs.notify("error", message)
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            rs.notify("success", "Username changed.")
            return self.redirect_show_user(rs, persona_id)

    @access("core_admin", {"POST"})
    @REQUESTdata(("activity", "bool"))
    def toggle_activity(self, rs, persona_id, activity):
        """Enable/disable an account."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id' : persona_id,
            'is_active' : activity,
        }
        change_note="Toggling activity to {}.".format(activity)
        num = self.coreproxy.adjust_persona(rs, data, change_note=change_note)
        self.notify_integer_success(rs, num)
        return self.redirect_show_user(rs, persona_id)

    @access("admin")
    def adjust_privileges_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_data_single(rs, persona_id)
        for bit in const.PrivilegeBits:
            if data['db_privileges'] & bit:
                rs.values.add('newprivileges', bit.value)
        return self.render(rs, "adjust_privileges", {
            'data' : data, 'bits' : const.PrivilegeBits})

    @access("admin", {"POST"})
    @REQUESTdata(("newprivileges", "[int]"))
    def adjust_privileges(self, rs, persona_id, newprivileges):
        """Allocate permissions. This is for global admins only."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id' : persona_id,
            'db_privileges' : sum(newprivileges),
        }
        change_note="Setting privileges to {}.".format(sum(newprivileges))
        num = self.coreproxy.adjust_persona(rs, data, change_note=change_note)
        self.notify_integer_success(rs, num)
        return self.redirect_show_user(rs, persona_id)

