#!/usr/bin/env python3

"""Services for the core realm."""

import datetime
import logging
import pytz
import uuid
from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access, ProxyShim,
    basic_redirect, connect_proxy, check_validation as check)
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
        concurrent accesses. Other errors are bugs.
        """
        if kind not in {"general", "database"}:
            kind = "general"
        return self.render(rs, "error", {
            'kind': kind, 'now': datetime.datetime.now(pytz.utc)})

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
        params = {'confirm_id': self.encode_parameter(
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
        code, message = self.coreproxy.change_password(
            rs, rs.user.persona_id, old_password, new_password)
        self.notify_return_code(rs, code, success="Password changed.",
                                error=message)
        if not code:
            rs.errors.append(("old_password", ValueError("Wrong password.")))
            self.logger.info(
                "Unsuccessful password change for persona {}.".format(
                    rs.user.persona_id))
            return self.change_password_form(rs)
        else:
            return self.redirect(rs, "core/index")

    @access("anonymous")
    def reset_password_form(self, rs):
        """Render form.

        This starts the process of anonymously resetting a password.
        """
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
            return self.reset_password_form(rs)
        self.do_mail(
            rs, "reset_password",
            {'To': (email,), 'Subject': 'CdEDB password reset'},
            {'email': self.encode_parameter(
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
        code, message = self.coreproxy.reset_password(rs, email)
        self.notify_return_code(rs, code, success="Password reset.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/reset_password_form")
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To': (email,),
                          'Subject': 'CdEDB password reset successful'},
                         {'password': message})
            return self.redirect(rs, "core/index")

    @access("core_admin", {"POST"})
    def admin_password_reset(self, rs, persona_id):
        """Administrative password reset."""
        data = self.coreproxy.get_data_one(rs, persona_id)
        code, message = self.coreproxy.reset_password(rs, data['username'])
        self.notify_return_code(rs, code, success="Password reset.",
                                error=message)
        if not code:
            return self.redirect_show_user(rs, persona_id)
        else:
            self.do_mail(rs, "password_reset_done",
                         {'To': (data['username'],),
                          'Subject': 'CdEDB password reset successful'},
                         {'password': message})
            return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_username_form(self, rs):
        """Render form."""
        return self.render(rs, "change_username")

    @access("persona")
    @REQUESTdata(("new_username", "email"))
    def send_username_change_link(self, rs, new_username):
        """First verify new name with test email."""
        if rs.errors:
            return self.change_username_form(rs)
        self.do_mail(rs, "change_username",
                     {'To': (new_username,),
                      'Subject': 'CdEDB username change'},
                     {'new_username': self.encode_parameter(
                         "core/do_username_change_form", "new_username",
                         new_username)})
        self.logger.info("Sent username change mail to {} for {}.".format(
            new_username, rs.user.username))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("persona")
    @REQUESTdata(("new_username", "#email"))
    def do_username_change_form(self, rs, new_username):
        """Email is now verified or we are admin."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/change_username_form")
        rs.values['new_username'] = self.encode_parameter(
            "core/do_username_change", "new_username", new_username)
        return self.render(rs, "do_username_change")

    @access("persona", {'POST'})
    @REQUESTdata(('new_username', '#email'), ('password', 'str'))
    def do_username_change(self, rs, new_username, password):
        """Now we can do the actual change."""
        if rs.errors:
            rs.notify("error", "Link expired")
            return self.redirect(rs, "core/change_username_form")
        code, message = self.coreproxy.change_username(
            rs, rs.user.persona_id, new_username, password)
        self.notify_return_code(rs, code, success="Username changed.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/username_change_form")
        else:
            return self.redirect(rs, "core/index")

    @access("core_admin")
    def admin_username_change_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_data_one(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access("core_admin", {'POST'})
    @REQUESTdata(('new_username', 'email'))
    def admin_username_change(self, rs, persona_id, new_username):
        """Change username without verification."""
        if rs.errors:
            return self.redirect(rs, "core/admin_username_change_form")
        code, message = self.coreproxy.change_username(
            rs, persona_id, new_username, password=None)
        self.notify_return_code(rs, code, success="Username changed.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/admin_username_change_form")
        else:
            return self.redirect_show_user(rs, persona_id)

    @access("core_admin", {"POST"})
    @REQUESTdata(("activity", "bool"))
    def toggle_activity(self, rs, persona_id, activity):
        """Enable/disable an account."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'is_active': activity,
        }
        change_note = "Toggling activity to {}.".format(activity)
        code = self.coreproxy.adjust_persona(rs, data, change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("admin")
    def adjust_privileges_form(self, rs, persona_id):
        """Render form."""
        data = self.coreproxy.get_data_one(rs, persona_id)
        if 'newprivileges' not in rs.values:
            for bit in const.PrivilegeBits:
                if data['db_privileges'] & bit:
                    rs.values.add('newprivileges', bit.value)
        return self.render(rs, "adjust_privileges", {
            'data': data, 'bits': const.PrivilegeBits})

    @access("admin", {"POST"})
    @REQUESTdata(("newprivileges", "[enum_privilegebits]"))
    def adjust_privileges(self, rs, persona_id, newprivileges):
        """Allocate permissions. This is for global admins only."""
        if rs.errors:
            return self.redirect_show_user(rs, persona_id)
        data = {
            'id': persona_id,
            'db_privileges': sum(newprivileges),
        }
        change_note = "Setting privileges to {}.".format(sum(newprivileges))
        code = self.coreproxy.adjust_persona(rs, data, change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def genesis_request_form(self, rs):
        """Render form."""
        return self.render(rs, "genesis_request")

    @access("anonymous", {"POST"})
    @REQUESTdata(("username", "email"), ("rationale", "str"),
                 ("full_name", "str"))
    def genesis_request(self, rs, username, rationale, full_name):
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        if not rs.errors and len(rationale) > self.conf.MAX_RATIONALE:
            rs.errors.append(("rationale", "Too long."))
        if rs.errors:
            return self.genesis_request_form(rs)
        case_id = self.coreproxy.genesis_request(rs, username, full_name,
                                                 rationale)
        if not case_id:
            rs.notify("error", "Failed.")
            return self.genesis_request_form(rs)
        self.do_mail(
            rs, "genesis_verify",
            {'To': (username,), 'Subject': 'CdEDB account request'},
            {'case_id': self.encode_parameter(
                "core/genesis_verify", "case_id", case_id),
             'full_name': full_name, })
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("case_id", "#int"))
    def genesis_verify(self, rs, case_id):
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.genesis_request_form(rs)
        code = self.coreproxy.genesis_verify(rs, case_id)
        self.notify_return_code(rs, code, success="Email verified.",
                                error="Verification failed.")
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @access("core_admin")
    def genesis_list_cases(self, rs):
        """Compile a list of genesis cases to review."""
        stati = (const.GenesisStati.to_review, const.GenesisStati.approved)
        data = self.coreproxy.genesis_list_cases(rs, stati=stati)
        review_ids = tuple(key for key in data
                           if (data[key]['case_status']
                               == const.GenesisStati.to_review))
        to_review = self.coreproxy.genesis_get_cases(rs, review_ids)
        approved = {k: v for k, v in data.items()
                    if v['case_status'] == const.GenesisStati.approved}
        return self.render(rs, "genesis_list_cases", {
            'to_review': to_review, 'approved': approved,
            'PersonaStati': const.PersonaStati,
            'GenesisStati': const.GenesisStati})

    @access("core_admin", {"POST"})
    @REQUESTdata(("case_id", "int"), ("case_status", "enum_genesisstati"),
                 ("persona_status", "enum_personastati_or_None"))
    def genesis_decide(self, rs, case_id, case_status, persona_status):
        """Approve or decline a genensis case.

        This sends an email with the link of the final creation page or a
        rejection note to the applicant.
        """
        if (case_status == const.GenesisStati.approved
                and persona_status is None):
            rs.errors.append(("persona_status",
                              ValueError("Must not be None.")))
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", "Case not to review.")
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'persona_status': persona_status,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
        }
        if case_status == const.GenesisStati.approved:
            data['secret'] = str(uuid.uuid4())
        code = self.coreproxy.genesis_modify_case(rs, data)
        if not code:
            rs.notify("error", "Failed.")
            return rs.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case_status == const.GenesisStati.approved:
            if case['persona_status'] == const.PersonaStati.event_user:
                realm = "event"
            else:
                raise RuntimeError("Impossible status.")
            self.do_mail(
                rs, "genesis_approved",
                {'To': (case['username'],),
                 'Subject': 'CdEDB account approved'},
                {'case': case, 'realm': realm})
            rs.notify("success", "Case approved.")
        else:
            self.do_mail(
                rs, "genesis_declined",
                {'To': (case['username'],),
                 'Subject': 'CdEDB account declined'},
                {'case': case,})
            rs.notify("info", "Case rejected.")
        return self.redirect(rs, "core/genesis_list_cases")

    @access("core_admin", {"POST"})
    @REQUESTdata(("case_id", "int"))
    def genesis_timeout(self, rs, case_id):
        """Abandon a genesis case.

        If a genesis case is approved, but the applicant loses interest,
        it remains dangling. Thus this enables to archive them.
        """
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case['case_status'] != const.GenesisStati.approved:
            rs.notify("error", "Case not approved.")
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'case_status': const.GenesisStati.timeout,
            'reviewer': rs.user.persona_id,
        }
        code = self.coreproxy.genesis_modify_case(rs, data)
        self.notify_return_code(rs, code, success="Case abandoned.")
        return self.redirect(rs, "core/genesis_list_cases")
