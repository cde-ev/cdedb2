#!/usr/bin/env python3

"""Services for the core realm."""

import logging
import uuid
from cdedb.frontend.common import (
    AbstractFrontend, REQUESTdata, REQUESTdatadict, access,
    basic_redirect, check_validation as check, merge_dicts)
from cdedb.common import PERSONA_STATUS_FIELDS, ProxyShim
from cdedb.backend.core import CoreBackend
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
        self.coreproxy = ProxyShim(CoreBackend(configpath))

    def finalize_session(self, rs):
        super().finalize_session(rs)

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
        return self.render(rs, "error", {'kind': kind})

    @access("anonymous", modi={"POST"})
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

    @access("persona", modi={"POST"})
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
        """FIXME"""
        if persona_id != confirm_id or rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/index")
        data = self.coreproxy.get_total_persona(rs, persona_id)
        return self.render(rs, "show_user", {'data': data})

    @access("core_admin")
    @REQUESTdata(("id_to_show", "cdedbid"), ("realm", "str"))
    def admin_show_user(self, rs, id_to_show, realm):
        """Allow admins to view any user data set."""
        if rs.errors or not "{}_admin".format(realm) in rs.user.roles:
            return self.redirect(rs, "core/index")
        return self.redirect_show_user(rs, id_to_show, realm)

    @access("persona")
    def change_user_form(self, rs):
        """FIXME Common entry point redirecting to user's realm."""
        data = self.coreproxy.get_total_persona(rs, rs.user.persona_id)
        data['generation'] = self.coreproxy.changelog_get_generation(
            rs, rs.user.persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "change_user", {'username': data['username']})

    @access("persona", modi={"POST"})
    @REQUESTdata(("generation", "int"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "bub_search")
    def change_user(self, rs, generation, data):
        """FIXME"""
        data['id'] = rs.user.persona_id
        data = check(rs, "persona", data)
        if rs.errors:
            return self.change_user_form(rs)
        change_note = "Normal dataset change."
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        if code < 0:
            ## send a mail since changes needing review should be seldom enough
            self.do_mail(
                rs, "pending_changes",
                {'To': (self.conf.MANAGEMENT_ADDRESS,),
                 'Subject': 'CdEDB pending changes',})
        return self.redirect_show_user(rs, rs.user.persona_id)

    @access("core_admin")
    def admin_change_user_form(self, rs, persona_id):
        """Common entry point redirecting to user's realm."""
        data = self.coreproxy.get_total_persona(rs, persona_id)
        data['generation'] = self.coreproxy.changelog_get_generation(
            rs, persona_id)
        merge_dicts(rs.values, data)
        return self.render(rs, "admin_change_user")


    @access("core_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("change_note", "str_or_None"))
    @REQUESTdatadict(
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "bub_search")
    def admin_change_user(self, rs, persona_id, generation, change_note, data):
        """FIXME"""
        data['id'] = rs.user.persona_id
        current = self.coreproxy.get_persona(rs, persona_id)
        for item in PERSONA_STATUS_FIELDS:
            data[item] = current[item]
        data = check(rs, "persona", data)
        if rs.errors:
            return self.admin_change_user_form(rs, persona_id)
        code = self.coreproxy.change_persona(rs, data, generation=generation,
                                             change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("admin")
    def change_privileges_form(self, rs, persona_id):
        """Render form."""
        merge_dicts(rs.values, rs.ambience['persona'])
        return self.render(rs, "change_privileges")

    @access("admin", modi={"POST"})
    @REQUESTdata(
        ("is_admin", "bool"), ("is_core_admin", "bool"),
        ("is_cde_admin", "bool"), ("is_event_admin", "bool"),
        ("is_ml_admin", "bool"), ("is_assembly_admin", "bool"))
    def change_privileges(self, rs, persona_id, is_admin, is_core_admin,
                          is_cde_admin, is_event_admin, is_ml_admin,
                          is_assembly_admin):
        """FIXME"""
        if rs.errors:
            return self.change_privileges_form(rs, persona_id)
        data = {
            "id": persona_id,
            "is_admin": is_admin,
            "is_core_admin": is_core_admin,
            "is_cde_admin": is_cde_admin,
            "is_event_admin": is_event_admin,
            "is_ml_admin": is_ml_admin,
            "is_assembly_admin": is_assembly_admin,
        }
        code = self.coreproxy.change_admin_bits(rs, data)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("persona")
    def change_password_form(self, rs):
        """Render form."""
        return self.render(rs, "change_password")

    @access("persona", modi={"POST"})
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
        success, message = self.coreproxy.make_reset_cookie(rs, email)
        if not success:
            rs.notify("error", message)
        self.do_mail(
            rs, "reset_password",
            {'To': (email,), 'Subject': 'CdEDB password reset'},
            {'email': self.encode_parameter(
                "core/do_password_reset_form", "email", email),
             'cookie': message})
        self.logger.info("Sent password reset mail to {} for IP {}.".format(
            email, rs.request.remote_addr))
        rs.notify("success", "Email sent.")
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata(("email", "#email"), ("cookie", "str"))
    def do_password_reset_form(self, rs, email, cookie):
        """Second form. Pretty similar to first form, but now we know, that
        the account owner actually wants the reset."""
        if rs.errors:
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        rs.values['email'] = self.encode_parameter(
            "core/do_password_reset", "email", email)
        return self.render(rs, "do_password_reset")

    @access("anonymous", modi={"POST"})
    @REQUESTdata(("email", "#email"), ("new_password", "str"),
                 ("cookie", "str"))
    def do_password_reset(self, rs, email, new_password, cookie):
        """Now we can reset to a new password."""
        new_password = check(rs, "password_strength", new_password,
                             "new_password")
        if rs.errors:
            # FIXME if strength fails let user retry
            rs.notify("error", "Link expired.")
            return self.redirect(rs, "core/reset_password_form")
        code, message = self.coreproxy.reset_password(rs, email, new_password,
                                                      cookie=cookie)
        self.notify_return_code(rs, code, success="Password reset.",
                                error=message)
        if not code:
            return self.redirect(rs, "core/reset_password_form")
        else:
            return self.redirect(rs, "core/index")

    @access("core_admin", modi={"POST"})
    def admin_password_reset(self, rs, persona_id):
        """Administrative password reset."""
        data = self.coreproxy.get_persona(rs, persona_id)
        code, message = self.coreproxy.make_reset_cookie(rs, data['username'])
        if code:
            code, message = self.coreproxy.new_password(
                rs, data['username'], cookie=message)
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

    @access("persona", modi={"POST"})
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
        data = self.coreproxy.get_persona(rs, persona_id)
        return self.render(rs, "admin_username_change", {'data': data})

    @access("core_admin", modi={"POST"})
    @REQUESTdata(('new_username', 'email_or_None'))
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

    @access("core_admin", modi={"POST"})
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
        code = self.coreproxy.change_persona(rs, data, change_note=change_note)
        self.notify_return_code(rs, code)
        return self.redirect_show_user(rs, persona_id)

    @access("anonymous")
    def genesis_request_form(self, rs):
        """Render form."""
        return self.render(rs, "genesis_request")

    @access("anonymous", modi={"POST"})
    @REQUESTdatadict("username", "notes", "given_names", "family_name", "realm")
    def genesis_request(self, rs, data):
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        data = check(rs, "genesis_case", data, creation=True)
        if not rs.errors and len(data['notes']) > self.conf.MAX_RATIONALE:
            rs.errors.append(("notes", ValueError("Too long.")))
        if rs.errors:
            return self.genesis_request_form(rs)
        case_id = self.coreproxy.genesis_request(rs, data)
        if not case_id:
            rs.notify("error", "Failed.")
            return self.genesis_request_form(rs)
        self.do_mail(
            rs, "genesis_verify",
            {'To': (data['username'],), 'Subject': 'CdEDB account request'},
            {'case_id': self.encode_parameter(
                "core/genesis_verify", "case_id", case_id),
             'given_names': data['given_names'],
             'family_name': data['family_name'],})
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
        review_ids = tuple(
            k for k in data
            if data[k]['case_status'] == const.GenesisStati.to_review)
        to_review = self.coreproxy.genesis_get_cases(rs, review_ids)
        approved = {k: v for k, v in data.items()
                    if v['case_status'] == const.GenesisStati.approved}
        return self.render(rs, "genesis_list_cases", {
            'to_review': to_review, 'approved': approved,})

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("case_status", "enum_genesisstati"),
                 ("realm", "str")) # FIXME maybe validate realm more?
    def genesis_decide(self, rs, case_id, case_status, realm):
        """Approve or decline a genensis case.

        This sends an email with the link of the final creation page or a
        rejection note to the applicant.
        """
        if rs.errors:
            return self.genesis_list_cases(rs)
        case = self.coreproxy.genesis_get_case(rs, case_id)
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", "Case not to review.")
            return self.genesis_list_cases(rs)
        data = {
            'id': case_id,
            'realm': realm,
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

    @access("core_admin", modi={"POST"})
    def genesis_timeout(self, rs, case_id):
        """Abandon a genesis case.

        If a genesis case is approved, but the applicant loses interest,
        it remains dangling. Thus this enables to archive them.
        """
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

    @access("core_admin")
    def list_pending_changes(self, rs):
        """List non-committed changelog entries."""
        pending = self.coreproxy.changelog_get_changes(
            rs, stati=(const.MemberChangeStati.pending,))
        return self.render(rs, "list_pending_changes", {'pending': pending})

    @access("core_admin")
    def inspect_change(self, rs, persona_id):
        """Look at a pending change."""
        history = self.coreproxy.changelog_get_history(rs, persona_id,
                                                       generations=None)
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

    @access("core_admin", modi={"POST"})
    @REQUESTdata(("generation", "int"), ("ack", "bool"))
    def resolve_change(self, rs, persona_id, generation, ack):
        """Make decision."""
        if rs.errors:
            return self.list_pending_changes(rs)
        code = self.coreproxy.changelog_resolve_change(rs, persona_id,
                                                       generation, ack)
        message = "Change comitted." if ack else "Change dropped."
        self.notify_return_code(rs, code, success=message)
        return self.redirect(rs, "core/list_pending_changes")

    @access("core_admin")
    @REQUESTdata(("stati", "[int]"), ("start", "int_or_None"),
                 ("stop", "int_or_None"))
    def view_changelog_meta(self, rs, stati, start, stop):
        """View changelog activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.coreproxy.retrieve_changelog_meta(rs, stati, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log}
            | {entry['reviewed_by'] for entry in log if entry['reviewed_by']}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        persona_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_changelog_meta", {
            'log': log, 'persona_data': persona_data})

    @access("core_admin")
    @REQUESTdata(("codes", "[int]"), ("persona_id", "cdedbid_or_None"),
                 ("start", "int_or_None"), ("stop", "int_or_None"))
    def view_log(self, rs, codes, persona_id, start, stop):
        """View activity."""
        start = start or 0
        stop = stop or 50
        ## no validation since the input stays valid, even if some options
        ## are lost
        log = self.coreproxy.retrieve_log(rs, codes, persona_id, start, stop)
        personas = (
            {entry['submitted_by'] for entry in log}
            | {entry['persona_id'] for entry in log if entry['persona_id']})
        user_data = self.coreproxy.get_personas(rs, personas)
        return self.render(rs, "view_log", {'log': log, 'user_data': user_data})

