#!/usr/bin/env python3

"""Services for the core realm."""

import logging
from cdedb.frontend.common import AbstractFrontend, REQUESTdata, \
    access_decorator_generator, ProxyShim, encodedparam_decorator_generator, \
    basic_redirect, connect_proxy
from cdedb.frontend.common import check_validation as check
import datetime
import pytz

access = access_decorator_generator(
        ("anonymous", "persona", "member", "core_admin", "admin"))
encodedparam = encodedparam_decorator_generator("core")

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

    @classmethod
    def finalize_session(cls, sessiondata):
        ret = super().finalize_session(sessiondata)
        if ret.role == "user":
            ## no user role in this realm
            ret.role = "persona"
        return ret

    @classmethod
    def build_navigation(cls, rs):
        return super().build_navigation(rs)

    @access("anonymous")
    @REQUESTdata("wants")
    @encodedparam("wants")
    def index(self, rs, wants=""):
        """Basic entry point.

        :param wants: URL to redirect to upon login
        """
        if wants:
            rs.values['wants'] = self.encode_parameter("core/login", "wants",
                                                       wants)
        return self.render(rs, "index")

    @access("anonymous")
    @REQUESTdata("kind")
    def error(self, rs, kind=""):
        """Fault page.

        This may happen upon a database serialization failure during
        concurrent accesses.
        """
        kind = check(rs, "printable_ascii", kind, "kind")
        if kind not in ("general", "database"):
            kind = "general"
        rs.notify("error", "{} error.".format(kind))
        return self.render(rs, "error",
                           {'kind' : kind,
                            'now' : datetime.datetime.now(pytz.utc)})

    @access("anonymous", ("POST",))
    @REQUESTdata("username", "password", "wants")
    @encodedparam("wants")
    def login(self, rs, username="", password="", wants=""):
        """Create session.

        :param wants: URL to redirect to
        """
        username = check(rs, "printable_ascii", username, "username")
        ## do not leak the password
        rs.values['password'] = ""
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
            self.redirect(rs, "core/index")
        rs.response.set_cookie("sessionkey", sessionkey)
        return rs.response

    @access("persona", ("POST",))
    def logout(self, rs):
        """Invalidate session."""
        self.coreproxy.logout(rs)
        self.redirect(rs, "core/index")
        rs.response.delete_cookie("sessionkey")
        return rs.response

    @access("persona")
    def mydata(self, rs):
        """Common entry point redirecting to user's realm."""
        return self.redirect(rs, "{}/mydata".format(rs.user.realm))

    @access("persona")
    def change_data_form(self, rs):
        """Common entry point redirecting to user's realm."""
        return self.redirect(rs, "{}/change_data_form".format(rs.user.realm))

    @access("persona")
    def change_password_form(self, rs):
        """Render form."""
        return self.render(rs, "change_password")

    @access("persona", ("POST",))
    @REQUESTdata("old_password", "new_password", "new_password2")
    def change_password(self, rs, old_password="", new_password="",
                        new_password2=""):
        """Update your own password."""
        old_password = check(rs, "str", old_password, "old_password")
        new_password = check(rs, "str", new_password, "new_password")
        new_password2 = check(rs, "str", new_password2, "new_password2")
        if new_password != new_password2:
            rs.errors.append(("new_password", ValueError("No match.")))
            rs.errors.append(("new_password2", ValueError("No match.")))
        new_password = check(rs, "password_strength", new_password,
                             "new_password")
        ## delete values so the user must resupply them
        for v in ('old_password', 'new_password', 'new_password2'):
            rs.values[v] = ""
        if rs.errors:
            return self.render(rs, "change_password")
        success, message = self.coreproxy.change_password(
            rs, rs.user.persona_id, old_password, new_password)
        if not success:
            rs.errors.append(("old_password", ValueError("Wrong password.")))
            rs.notify("error", message)
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
            return self.render(rs, "change_password")
        else:
            rs.notify("success", "Password changed.")
            return self.redirect(rs, "core/index")

    @access("anonymous")
    def reset_password_form(self, rs):
        """Render form."""
        return self.render(rs, "reset_password")

    @access("anonymous")
    @REQUESTdata("email")
    def send_password_reset_link(self, rs, email=""):
        """First send a confirmation mail, to prevent an adversary from
        changing random passwords."""
        email = check(rs, "email", email, "email")
        if rs.errors:
            return self.render(rs, "reset_password")
        exists = self.coreproxy.verify_existence(rs, email)
        if not exists:
            rs.notify("error", "Email non-existant.")
            return self.render(rs, "reset_password")
        self.do_mail(
            rs, "reset_password",
            {'To' : (email,), 'Subject' : 'CdEDB password reset'},
            {'email' : self.encode_parameter(
                "core/do_password_reset_form", "email", email)})
        self.logger.info("Sent password reset mail to {} for IP {}.".format(
            email, rs.request.remote_addr))
        rs.notify("success", "Email sent.")
        return self.render(rs, "index")

    @access("anonymous")
    @REQUESTdata("email")
    @encodedparam("email")
    def do_password_reset_form(self, rs, email=""):
        """Second form. Pretty similar to first form, but now we know, that
        the account owner actually wants the reset."""
        email = check(rs, "email", email, "email")
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.render(rs, "reset_password")
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email)
        return self.render(rs, "do_password_reset")

    @access("anonymous", ("POST",))
    @REQUESTdata("email")
    @encodedparam("email")
    def do_password_reset(self, rs, email=""):
        """Now we can send an email with a new password."""
        email = check(rs, "email", email, "email")
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.render(rs, "reset_password")
        success, message = self.coreproxy.reset_password(rs, email)
        if not success:
            rs.notify("error", message)
            return self.render(rs, "reset_password")
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To' : (email,),
                          'Subject' : 'CdEDB password reset successful'},
                         {'password' : message})
            rs.notify("success", "Password reset.")
            return self.redirect(rs, "core/index")

    @access("persona")
    def change_username_form(self, rs):
        """Render form."""
        # TODO implement changelog functionality, then redirect on realm
        return self.render(rs, "change_username")

    @access("persona")
    @REQUESTdata("new_username")
    def send_username_change_link(self, rs, new_username=""):
        """Verify new name with test email."""
        # TODO implement changelog functionality, then redirect on realm
        new_username = check(rs, "email", new_username, "new_username")
        if rs.errors:
            return self.render(rs, "change_username")
        self.do_mail(rs, "change_username",
                     {'To' : (new_username,), 'Subject' : 'CdEDB username change'},
                     {'new_username' : self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username)})
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
        rs.notify("success", "Email sent.")
        return self.render(rs, "index")

    @access("persona")
    @REQUESTdata("new_username")
    @encodedparam("new_username")
    def do_username_change_form(self, rs, new_username=""):
        """Email is now verified."""
        # TODO implement changelog functionality, then redirect on realm
        new_username = check(rs, "email", new_username, "new_username")
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.render(rs, "change_username")
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username)
        return self.render(rs, "do_username_change")

    @access("persona", ('POST',))
    @REQUESTdata('new_username', 'password')
    @encodedparam('new_username')
    def do_username_change(self, rs, new_username="", password=""):
        """Now we can do the actual change."""
        # TODO implement changelog functionality, then redirect on realm
        new_username = check(rs, 'email', new_username, "new_username")
        password = check(rs, 'str', password, "password")
        ## do not leak the password
        rs.values['password'] = ""
        if rs.errors:
            rs.values['new_username'] = self.encode_parameter(
                "core/do_username_change", "new_username", new_username)
            return self.render(rs, "do_username_change")
        success, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        if not success:
            rs.notify("error", message)
            rs.values['new_username'] = self.encode_parameter(
                "core/do_username_change", "new_username", new_username)
            return self.render(rs, "do_username_change")
        else:
            rs.notify("success", "Username changed.")
            return self.redirect(rs, "core/index")
