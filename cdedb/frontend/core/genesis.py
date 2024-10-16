#!/usr/bin/env python3

"""Genesis specific services for the core realm."""

import collections
import datetime
from typing import Optional

import werkzeug.exceptions
from werkzeug import Response

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, GenesisDecision, RequestState, merge_dicts, now
from cdedb.common.fields import REALM_SPECIFIC_GENESIS_FIELDS
from cdedb.common.n_ import n_
from cdedb.common.validation.validate import (
    GENESIS_CASE_EXPOSED_FIELDS,
    PERSONA_COMMON_FIELDS,
)
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    REQUESTfile,
    access,
    check_validation as check,
    periodic,
)
from cdedb.frontend.core.base import CoreBaseFrontend

# Name of each realm's option in the genesis form
GenesisRealmOptionName = collections.namedtuple(
    'GenesisRealmOptionName', ['realm', 'name'])
GENESIS_REALM_OPTION_NAMES = (
    GenesisRealmOptionName("cde", n_("CdE membership & events")),
    GenesisRealmOptionName("event", n_("CdE events")),
    GenesisRealmOptionName("ml", n_("CdE mailinglist")))


class CoreGenesisMixin(CoreBaseFrontend):
    @access("anonymous")
    @REQUESTdata("realm")
    def genesis_request_form(self, rs: RequestState, realm: Optional[str] = None,
                             ) -> Response:
        """Render form."""
        rs.ignore_validation_errors()
        allowed_genders = set(x for x in const.Genders
                              if x != const.Genders.not_specified)
        realm_options = [(option.realm, rs.gettext(option.name))
                         for option in GENESIS_REALM_OPTION_NAMES
                         if option.realm in REALM_SPECIFIC_GENESIS_FIELDS]
        meta_info = self.coreproxy.get_meta_info(rs)
        return self.render(rs, "genesis/genesis_request", {
            'max_rationale': self.conf["MAX_RATIONALE"],
            'allowed_genders': allowed_genders,
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'realm_options': realm_options,
            'meta_info': meta_info,
        })

    @access("anonymous", modi={"POST"})
    @REQUESTdatadict(*GENESIS_CASE_EXPOSED_FIELDS)
    @REQUESTfile("attachment")
    @REQUESTdata("attachment_filename")
    def genesis_request(self, rs: RequestState, data: CdEDBObject,
                        attachment: Optional[werkzeug.datastructures.FileStorage],
                        attachment_filename: Optional[str] = None) -> Response:
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        rs.values['attachment_hash'], rs.values['attachment_filename'] =\
            self.locate_or_store_attachment(
                rs, self.coreproxy.get_genesis_attachment_store(rs), attachment,
                data.get('attachment_hash'), attachment_filename)
        if ('attachment_hash' in REALM_SPECIFIC_GENESIS_FIELDS.get(data['realm'], {})
                and not rs.values['attachment_hash']):
            e = ("attachment", ValueError(n_("Attachment missing.")))
            rs.append_validation_error(e)
        data['attachment_hash'] = rs.values['attachment_hash']

        data = check(rs, vtypes.GenesisCase, data, creation=True)
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        assert data is not None
        # past events and courses may not be set here
        data['pevent_id'] = None
        data['pcourse_id'] = None
        if len(data['notes']) > self.conf["MAX_RATIONALE"]:
            rs.append_validation_error(
                ("notes", ValueError(n_("Rationale too long."))))
        # We dont actually want gender == not_specified as a valid option if it
        # is required for the requested realm)
        if 'gender' in REALM_SPECIFIC_GENESIS_FIELDS.get(data['realm'], {}):
            if data['gender'] == const.Genders.not_specified:
                rs.append_validation_error(
                    ("gender", ValueError(n_(
                        "Must specify gender for %(realm)s realm."),
                        {"realm": data["realm"]})))
        if 'birthday' in REALM_SPECIFIC_GENESIS_FIELDS.get(data['realm'], {}):
            if data['birthday'] == datetime.date.min:
                rs.append_validation_error(
                    ("birthday", ValueError(n_("Must not be empty."))))
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        if self.coreproxy.verify_existence(rs, data['username']):
            existing_id = self.coreproxy.genesis_case_by_email(
                rs, data['username'])
            if existing_id and existing_id > 0:
                # TODO this case is kind of a hack since it throws
                # away the information entered by the user, but in
                # theory this should not happen too often (reality
                # notwithstanding)
                rs.notify("info", n_("Confirmation email has been resent."))
                case_id = existing_id
            elif existing_id and existing_id < 0:
                rs.notify("info", n_("Your request is currently pending review."))
                return self.redirect(rs, "core/index")
            else:
                rs.notify("error", n_("Email address already in DB. Reset password."))
                return self.redirect(rs, "core/index")
        else:
            new_id = self.coreproxy.genesis_request(rs, data)
            if not new_id:
                rs.notify("error", n_("Failed."))
                return self.genesis_request_form(rs)
            case_id = new_id

        # Send verification mail for new case or resend for old case.
        self.do_mail(rs, "genesis/genesis_verify",
                     {
                         'To': (data['username'],),
                         'Subject': "Accountanfrage verifizieren",
                     },
                     {
                         'genesis_case_id': self.encode_parameter(
                             "core/genesis_verify", "genesis_case_id",
                             str(case_id), persona_id=None),
                         'given_names': data['given_names'],
                         'family_name': data['family_name'],
                     })
        rs.notify(
            "success",
            n_("We just sent you an email. To complete your account request, please"
               " follow the link contained in the email."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata("#genesis_case_id")
    def genesis_verify(self, rs: RequestState, genesis_case_id: int,
                       ) -> Response:
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        code, _ = self.coreproxy.genesis_verify(rs, genesis_case_id)
        rs.notify_return_code(
            code,
            error=n_("Verification failed. Please contact the administrators."),
            success=n_("Email verified. Wait for moderation. "
                       "You will be notified by mail."),
            info=n_("This account request was already verified."),
        )
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @periodic("genesis_remind")
    def genesis_remind(self, rs: RequestState, store: CdEDBObject,
                       ) -> CdEDBObject:
        """Cron job for genesis cases to review.

        Send a reminder after four hours and then daily.
        """
        current = now()
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,))
        old = set(store.get('ids', [])) & set(data)
        new = set(data) - set(old)
        remind = False
        if any(data[anid]['ctime'] + datetime.timedelta(hours=4) < current
               for anid in new):
            remind = True
        if old and current.timestamp() > store.get('tstamp', 0) + 24*60*60:
            remind = True
        if remind:
            stati = (const.GenesisStati.to_review,)
            cde_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["cde"]))
            event_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["event"]))
            ml_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["ml"]))
            assembly_count = len(self.coreproxy.genesis_list_cases(
                rs, stati=stati, realms=["assembly"]))
            notify = {self.conf["MANAGEMENT_ADDRESS"]}
            if cde_count:
                notify |= {self.conf["CDE_ADMIN_ADDRESS"]}
            if event_count:
                notify |= {self.conf["EVENT_ADMIN_ADDRESS"]}
            if ml_count:
                notify |= {self.conf["ML_ADMIN_ADDRESS"]}
            if assembly_count:
                notify |= {self.conf["ASSEMBLY_ADMIN_ADDRESS"]}
            self.do_mail(
                rs, "genesis/genesis_requests_pending",
                {'To': tuple(notify),
                 'Subject': "Offene CdEDB Accountanfragen"},
                {'count': len(data)})
            store = {
                'tstamp': current.timestamp(),
                'ids': list(data),
            }
        return store

    @periodic("genesis_forget", period=96)
    def genesis_forget(self, rs: RequestState, store: CdEDBObject,
                       ) -> CdEDBObject:
        """Cron job for deleting successful, unconfirmed or rejected genesis cases.

        This allows the username to be used once more.
        """
        stati = const.GenesisStati.finalized_stati() | {const.GenesisStati.unconfirmed}
        cases = self.coreproxy.genesis_list_cases(rs, stati=stati)

        delete = tuple(case["id"] for case in cases.values() if
                       case["ctime"] < now() - self.conf["GENESIS_CLEANUP_TIMEOUT"]
                       or (case['case_status'] == const.GenesisStati.unconfirmed and
                           case["ctime"] < now() - self.conf["PARAMETER_TIMEOUT"]))

        count = 0
        for genesis_case_id in delete:
            count += self.coreproxy.delete_genesis_case(rs, genesis_case_id)

        attachment_count = self.coreproxy.get_genesis_attachment_store(rs).forget(
            rs, self.coreproxy.get_genesis_attachment_usage)

        if count or attachment_count:
            self.logger.info(f"genesis_forget: Deleted {count} genesis cases and"
                             f" {attachment_count} attachments")

        return store

    @access("anonymous")
    def genesis_get_attachment(self, rs: RequestState, attachment_hash: str,
                               ) -> Response:
        """Retrieve attachment for genesis case."""
        path = self.coreproxy.get_genesis_attachment_store(rs).get_path(attachment_hash)
        if not path.is_file():
            raise werkzeug.exceptions.NotFound(n_("File does not exist."))
        return self.send_file(rs, path=path, mimetype='application/pdf')

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_list_cases(self, rs: RequestState) -> Response:
        """Compile a list of genesis cases to review."""
        realms = [realm for realm in REALM_SPECIFIC_GENESIS_FIELDS
                  if {f"{realm}_admin", 'core_admin'} & rs.user.roles]
        data = self.coreproxy.genesis_list_cases(
            rs, realms=realms, stati={
                const.GenesisStati.to_review, const.GenesisStati.successful,
                const.GenesisStati.existing_updated, const.GenesisStati.rejected})
        cases = self.coreproxy.genesis_get_cases(rs, set(data))
        current_cases_by_realm = {
            realm: {k: v for k, v in cases.items() if v['realm'] == realm
                        and v['case_status'] == const.GenesisStati.to_review}
            for realm in realms}
        concluded_cases = {k: v for k, v in cases.items()
                           if v['case_status'] != const.GenesisStati.to_review}
        created_account_ids = [case['persona_id'] for case in concluded_cases.values()
                               if case['persona_id']]
        personas = self.coreproxy.get_personas(rs, created_account_ids)
        return self.render(rs, "genesis/genesis_list_cases", {
            'current_cases_by_realm': current_cases_by_realm,
            'concluded_cases': concluded_cases, 'personas': personas})

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_show_case(self, rs: RequestState, genesis_case_id: int,
                          ) -> Response:
        """View a specific case."""
        case = rs.ambience['genesis_case']
        if not self.is_admin(rs) and f"{case['realm']}_admin" not in rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        persona = reviewer = pevent = pcourse = None
        if case['persona_id']:
            persona = self.coreproxy.get_persona(rs, case['persona_id'])
        if case['reviewer']:
            reviewer = self.coreproxy.get_persona(rs, case['reviewer'])
        if "event" in rs.user.roles:
            # e.g. for ml-only ml admins
            if case['pevent_id']:
                pevent = self.pasteventproxy.get_past_event(rs, case['pevent_id'])
            if case['pcourse_id']:
                pcourse = self.pasteventproxy.get_past_course(rs, case['pcourse_id'])
        persona_data = {k: v for k, v in case.items() if k in PERSONA_COMMON_FIELDS}
        # Set a valid placeholder value, that will pass the input validation.
        persona_data['id'] = 1
        # We don't actually compare genders, so this is to make sure it is not empty.
        persona_data['gender'] = const.Genders.not_specified
        doppelgangers = self.coreproxy.find_doppelgangers(rs, persona_data)
        non_editable_doppelgangers = {
            persona_id: not persona['may_be_edited']
            for persona_id, persona in doppelgangers.items()
        }
        title_map = {
            persona_id: rs.gettext("Insufficient admin privileges.")
            for persona_id, not_relative_admin in non_editable_doppelgangers.items()
            if not_relative_admin
        }
        return self.render(rs, "genesis/genesis_show_case", {
            'reviewer': reviewer, 'pevent': pevent, 'pcourse': pcourse,
            'persona': persona, 'doppelgangers': doppelgangers,
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'disabled_radios': non_editable_doppelgangers, 'title_map': title_map,
        })

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_modify_form(self, rs: RequestState, genesis_case_id: int,
                            ) -> Response:
        """Edit a specific case it."""
        case = rs.ambience['genesis_case']
        if not self.is_admin(rs) and f"{case['realm']}_admin" not in rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        merge_dicts(rs.values, case)
        realm_options = [(option.realm, rs.gettext(option.name))
                         for option in GENESIS_REALM_OPTION_NAMES
                         if option.realm in REALM_SPECIFIC_GENESIS_FIELDS]

        courses: dict[int, str] = {}
        if case['pevent_id']:
            courses = self.pasteventproxy.list_past_courses(rs, case['pevent_id'])
        choices = {"pevent_id": self.pasteventproxy.list_past_events(rs),
                   "pcourse_id": courses}

        return self.render(rs, "genesis/genesis_modify_form", {
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'realm_options': realm_options, 'choices': choices})

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdatadict(*GENESIS_CASE_EXPOSED_FIELDS)
    def genesis_modify(self, rs: RequestState, genesis_case_id: int,
                       data: CdEDBObject) -> Response:
        """Edit a case to fix potential issues before creation."""
        data['id'] = genesis_case_id
        # In contrast to the genesis_request, the attachment can not be changed here.
        del data['attachment_hash']
        data = check(
            rs, vtypes.GenesisCase, data)
        if rs.has_validation_errors():
            return self.genesis_modify_form(rs, genesis_case_id)
        assert data is not None
        if data['username'] != rs.ambience['genesis_case']['username']:
            if self.coreproxy.verify_existence(rs, data['username']):
                rs.append_validation_error(
                    ("username", ValueError(n_("Email address already taken."))))
        if data.get('pcourse_id'):
            # Capture both course without event and with unassociated event
            if data.get('pevent_id') != self.pasteventproxy.get_past_course(
                    rs, data['pcourse_id'])['pevent_id']:
                e = ValueError(n_("Course not associated with past event specified."))
                rs.extend_validation_errors((("pcourse_id", e), ("pevent_id", e)))
        if rs.has_validation_errors():
            return self.genesis_modify_form(rs, genesis_case_id)

        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        code = self.coreproxy.genesis_modify_case(rs, data)
        rs.notify_return_code(code)
        return self.redirect(rs, "core/genesis_show_case")

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdata("decision", "persona_id")
    def genesis_decide(self, rs: RequestState, genesis_case_id: int,
                       decision: GenesisDecision, persona_id: Optional[int],
                       ) -> Response:
        """Approve or decline a genensis case.

        This either creates a new account or declines account creation.
        If the request is declined, an existing account can optionally be dearchived
        and/or updated.
        """
        if rs.has_validation_errors():
            return self.genesis_show_case(rs, genesis_case_id)
        case = rs.ambience['genesis_case']

        # Do privilege and sanity checks.
        if not self.is_admin(rs) and f"{case['realm']}_admin" not in rs.user.roles:
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if decision.is_create():
            if self.coreproxy.verify_existence(
                    rs, case['username'], include_genesis=False):
                rs.notify("error", n_("Email address already taken."))
                return self.redirect(rs, "core/genesis_show_case")
            if persona_id:
                rs.notify("error", n_("Persona selected, but genesis case approved."))
                return self.redirect(rs, "core/genesis_show_case")
        if decision.is_update():
            if not persona_id:
                rs.notify("error", n_("No persona selected."))
                return self.redirect(rs, "core/genesis_show_case")
            elif not self.coreproxy.verify_persona(
                    rs, persona_id, (case['realm'],)):
                rs.notify("error", n_("Invalid persona for update."
                                      " Add additional realm first: %(realm)s."),
                          {'realm': case['realm']})
                return self.redirect(rs, "core/genesis_show_case")
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.redirect(rs, "core/genesis_show_case")

        # Apply the decision.
        persona_id = self.coreproxy.genesis_decide(
            rs, genesis_case_id, decision, persona_id)
        if not persona_id:  # Purely an error case. # pragma: no cover
            rs.notify("error", n_("Failed."))
            return self.genesis_show_case(rs, genesis_case_id)

        if ((decision.is_create() or decision.is_update()) and case['pevent_id']
                and case['realm'] == 'cde'):
            code = self.pasteventproxy.add_participant(
                rs, pevent_id=case['pevent_id'], pcourse_id=case['pcourse_id'],
                persona_id=persona_id)
            if not code:  # pragma: no cover
                rs.notify(
                    "error", n_("Past event attendance could not be established."))

        # Send notification to the user, depending on decision.
        if decision.is_create():
            persona = self.coreproxy.get_persona(rs, persona_id)
            self.send_welcome_mail(rs, persona)
            rs.notify("success", n_("Case approved."))
        elif decision.is_update():
            persona = self.coreproxy.get_persona(rs, persona_id)
            _, cookie = self.coreproxy.make_reset_cookie(
                rs, persona['username'], timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            email = self.encode_parameter(
                "core/do_password_reset_form", "email", persona['username'],
                persona_id=None, timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            self.do_mail(
                rs, "genesis/genesis_updated",
                {'To': (persona['username'],), 'Subject': "CdEDB-Account reaktiviert"},
                {'persona': persona, 'email': email, 'cookie': cookie})
            rs.notify("success", n_("User updated."))
        else:
            self.do_mail(
                rs, "genesis/genesis_declined",
                {'To': (case['username'],),
                 'Subject': "CdEDB Accountanfrage abgelehnt"},
            )
            rs.notify("info", n_("Case rejected."))
        return self.redirect(rs, "core/genesis_list_cases")
