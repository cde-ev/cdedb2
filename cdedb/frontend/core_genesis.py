#!/usr/bin/env python3

"""Genesis specific services for the core realm."""

import collections
import datetime
from typing import Dict, Optional

import magic
import werkzeug.exceptions
from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    REALM_SPECIFIC_GENESIS_FIELDS, CdEDBObject, RequestState, merge_dicts, n_, now,
)

from cdedb.frontend.common import (
    REQUESTdata, REQUESTdatadict, REQUESTfile, access, check_validation as check,
    periodic, TransactionObserver,
)
from cdedb.frontend.core_base import CoreBaseFrontend
from cdedb.validation import (
    GENESIS_CASE_EXPOSED_FIELDS, PERSONA_COMMON_FIELDS
)

# Name of each realm's option in the genesis form
GenesisRealmOptionName = collections.namedtuple(
    'GenesisRealmOptionName', ['realm', 'name'])
GENESIS_REALM_OPTION_NAMES = (
    GenesisRealmOptionName("event", n_("CdE event")),
    GenesisRealmOptionName("cde", n_("CdE membership")),
    GenesisRealmOptionName("assembly", n_("CdE members' assembly")),
    GenesisRealmOptionName("ml", n_("CdE mailinglist")))


class CoreGenesisMixin(CoreBaseFrontend):
    @access("anonymous")
    @REQUESTdata("realm")
    def genesis_request_form(self, rs: RequestState, realm: Optional[str] = None
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
    @REQUESTdata("attachment_filename", "ignore_warnings")
    def genesis_request(self, rs: RequestState, data: CdEDBObject,
                        attachment: Optional[werkzeug.datastructures.FileStorage],
                        attachment_filename: str = None,
                        ignore_warnings: bool = False) -> Response:
        """Voice the desire to become a persona.

        This initiates the genesis process.
        """
        attachment_data = None
        if attachment:
            attachment_filename = attachment.filename
            attachment_data = check(rs, vtypes.PDFFile, attachment, 'attachment')
        if attachment_data:
            myhash = self.coreproxy.genesis_set_attachment(rs, attachment_data)
            data['attachment_hash'] = myhash
            rs.values['attachment_hash'] = myhash
            rs.values['attachment_filename'] = attachment_filename
        elif data['attachment_hash']:
            attachment_stored = self.coreproxy.genesis_check_attachment(
                rs, data['attachment_hash'])
            if not attachment_stored:
                data['attachment_hash'] = None
                e = ("attachment", ValueError(n_(
                    "It seems like you took too long and "
                    "your previous upload was deleted.")))
                rs.append_validation_error(e)
        elif 'attachment_hash' in REALM_SPECIFIC_GENESIS_FIELDS.get(data['realm'], {}):
            e = ("attachment", ValueError(n_("Attachment missing.")))
            rs.append_validation_error(e)

        data = check(rs, vtypes.GenesisCase, data, creation=True,
                     _ignore_warnings=ignore_warnings)
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
            if existing_id:
                # TODO this case is kind of a hack since it throws
                # away the information entered by the user, but in
                # theory this should not happen too often (reality
                # notwithstanding)
                rs.notify("info", n_("Confirmation email has been resent."))
                case_id = existing_id
            else:
                rs.notify("error",
                          n_("Email address already in DB. Reset password."))
                return self.redirect(rs, "core/index")
        else:
            new_id = self.coreproxy.genesis_request(
                rs, data, ignore_warnings=ignore_warnings)
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
            n_("Email sent. Please follow the link contained in the email."))
        return self.redirect(rs, "core/index")

    @access("anonymous")
    @REQUESTdata("#genesis_case_id")
    def genesis_verify(self, rs: RequestState, genesis_case_id: int
                       ) -> Response:
        """Verify the email address entered in :py:meth:`genesis_request`.

        This is not a POST since the link is shared via email.
        """
        if rs.has_validation_errors():
            return self.genesis_request_form(rs)
        code, realm = self.coreproxy.genesis_verify(rs, genesis_case_id)
        self.notify_return_code(
            rs, code,
            error=n_("Verification failed. Please contact the administrators."),
            success=n_("Email verified. Wait for moderation. "
                       "You will be notified by mail."),
            info=n_("This account request was already verified.")
        )
        if not code:
            return self.redirect(rs, "core/genesis_request_form")
        return self.redirect(rs, "core/index")

    @periodic("genesis_remind")
    def genesis_remind(self, rs: RequestState, store: CdEDBObject
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
    def genesis_forget(self, rs: RequestState, store: CdEDBObject
                       ) -> CdEDBObject:
        """Cron job for deleting unconfirmed or rejected genesis cases.

        This allows the username to be used once more.
        """
        stati = (const.GenesisStati.unconfirmed, const.GenesisStati.rejected)
        cases = self.coreproxy.genesis_list_cases(
            rs, stati=stati)

        delete = tuple(case["id"] for case in cases.values() if
                       case["ctime"] < now() - self.conf["PARAMETER_TIMEOUT"])

        count = 0
        for genesis_case_id in delete:
            count += self.coreproxy.delete_genesis_case(rs, genesis_case_id)

        attachment_count = self.coreproxy.genesis_forget_attachments(rs)

        if count or attachment_count:
            self.logger.info(f"genesis_forget: Deleted {count} genesis cases and"
                             f" {attachment_count} attachments")

        return store

    @access("core_admin", *("{}_admin".format(realm)
                            for realm, fields in
                            REALM_SPECIFIC_GENESIS_FIELDS.items()
                            if "attachment_hash" in fields))
    def genesis_get_attachment(self, rs: RequestState, attachment_hash: str
                               ) -> Response:
        """Retrieve attachment for genesis case."""
        data = self.coreproxy.genesis_get_attachment(rs, attachment_hash)
        mimetype = None
        if data:
            mimetype = magic.from_buffer(data, mime=True)
        return self.send_file(rs, data=data, mimetype=mimetype)

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_list_cases(self, rs: RequestState) -> Response:
        """Compile a list of genesis cases to review."""
        realms = [realm for realm in REALM_SPECIFIC_GENESIS_FIELDS
                  if {"{}_admin".format(realm), 'core_admin'} & rs.user.roles]
        data = self.coreproxy.genesis_list_cases(
            rs, stati=(const.GenesisStati.to_review,), realms=realms)
        cases = self.coreproxy.genesis_get_cases(rs, set(data))
        cases_by_realm = {
            realm: {k: v for k, v in cases.items() if v['realm'] == realm}
            for realm in realms}
        return self.render(rs, "genesis/genesis_list_cases", {
            'cases_by_realm': cases_by_realm})

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_show_case(self, rs: RequestState, genesis_case_id: int
                          ) -> Response:
        """View a specific case."""
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        reviewer = pevent = pcourse = None
        if case['reviewer']:
            reviewer = self.coreproxy.get_persona(rs, case['reviewer'])
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
        return self.render(rs, "genesis/genesis_show_case", {
            'reviewer': reviewer, 'pevent': pevent, 'pcourse': pcourse,
            'doppelgangers': doppelgangers,
        })

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def genesis_modify_form(self, rs: RequestState, genesis_case_id: int
                            ) -> Response:
        """Edit a specific case it."""
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        merge_dicts(rs.values, case)
        realm_options = [(option.realm, rs.gettext(option.name))
                         for option in GENESIS_REALM_OPTION_NAMES
                         if option.realm in REALM_SPECIFIC_GENESIS_FIELDS]

        courses: Dict[int, str] = {}
        if case['pevent_id']:
            courses = self.pasteventproxy.list_past_courses(rs, case['pevent_id'])
        choices = {"pevent_id": self.pasteventproxy.list_past_events(rs),
                   "pcourse_id": courses}

        return self.render(rs, "genesis/genesis_modify_form", {
            'REALM_SPECIFIC_GENESIS_FIELDS': REALM_SPECIFIC_GENESIS_FIELDS,
            'realm_options': realm_options, 'choices': choices})

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdatadict(*GENESIS_CASE_EXPOSED_FIELDS)
    @REQUESTdata("ignore_warnings")
    def genesis_modify(self, rs: RequestState, genesis_case_id: int,
                       data: CdEDBObject, ignore_warnings: bool = False
                       ) -> Response:
        """Edit a case to fix potential issues before creation."""
        data['id'] = genesis_case_id
        # In contrast to the genesis_request, the attachment can not be changed here.
        del data['attachment_hash']
        data = check(
            rs, vtypes.GenesisCase, data, _ignore_warnings=ignore_warnings)
        if rs.has_validation_errors():
            return self.genesis_modify_form(rs, genesis_case_id)
        assert data is not None
        if data['username'] != rs.ambience['genesis_case']['username']:
            if self.coreproxy.verify_existence(rs, data['username']):
                rs.append_validation_error(
                    ("username", ValueError(n_("Email address already taken."))))
                rs.ignore_validation_errors()
                return self.genesis_modify_form(rs, genesis_case_id)
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        code = self.coreproxy.genesis_modify_case(
            rs, data, ignore_warnings=ignore_warnings)
        self.notify_return_code(rs, code)
        return self.redirect(rs, "core/genesis_show_case")

    @access("core_admin", *("{}_admin".format(realm)
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS),
            modi={"POST"})
    @REQUESTdata("case_status")
    def genesis_decide(self, rs: RequestState, genesis_case_id: int,
                       case_status: const.GenesisStati) -> Response:
        """Approve or decline a genensis case.

        This either creates a new account or declines account creation.
        """
        if rs.has_validation_errors():
            return self.genesis_list_cases(rs)
        case = rs.ambience['genesis_case']
        if (not self.is_admin(rs)
                and "{}_admin".format(case['realm']) not in rs.user.roles):
            raise werkzeug.exceptions.Forbidden(n_("Not privileged."))
        if case['case_status'] != const.GenesisStati.to_review:
            rs.notify("error", n_("Case not to review."))
            return self.genesis_list_cases(rs)
        data = {
            'id': genesis_case_id,
            'case_status': case_status,
            'reviewer': rs.user.persona_id,
            'realm': case['realm'],
        }
        with TransactionObserver(rs, self, "genesis_decide"):
            code = self.coreproxy.genesis_modify_case(rs, data)
            success = bool(code)
            new_id = None
            pcode = 1
            if success and data['case_status'] == const.GenesisStati.approved:
                new_id = self.coreproxy.genesis(rs, genesis_case_id)
                if case['pevent_id']:
                    pcode = self.pasteventproxy.add_participant(
                        rs, pevent_id=case['pevent_id'], pcourse_id=case['pcourse_id'],
                        persona_id=new_id)
                success = bool(new_id)
        if not pcode and success:
            rs.notify("error", n_("Past event attendance could not be established."))
            return self.genesis_list_cases(rs)
        if not success:
            rs.notify("error", n_("Failed."))
            return self.genesis_list_cases(rs)
        if case_status == const.GenesisStati.approved and new_id:
            persona = self.coreproxy.get_persona(rs, new_id)
            meta_info = self.coreproxy.get_meta_info(rs)
            success, cookie = self.coreproxy.make_reset_cookie(
                rs, persona['username'],
                timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            email = self.encode_parameter("core/do_password_reset_form", "email",
                                          persona['username'], persona_id=None,
                                          timeout=self.conf["EMAIL_PARAMETER_TIMEOUT"])
            self.do_mail(
                rs, "welcome",
                {'To': (persona['username'],), 'Subject': "Aufnahme in den CdE"},
                {'data': persona, 'email': email, 'cookie': cookie,
                 'fee': self.conf['MEMBERSHIP_FEE'], 'meta_info': meta_info})
            rs.notify("success", n_("Case approved."))
        else:
            self.do_mail(
                rs, "genesis/genesis_declined",
                {'To': (case['username'],),
                 'Subject': "CdEDB Accountanfrage abgelehnt"},
            )
            rs.notify("info", n_("Case rejected."))
        return self.redirect(rs, "core/genesis_list_cases")
