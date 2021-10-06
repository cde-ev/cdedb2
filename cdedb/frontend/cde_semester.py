#!/usr/bin/env python3

"""Semester management services for the cde realm."""

import datetime
from typing import Collection, Optional

from werkzeug import Response

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.common import (
    LOG_FIELDS_COMMON, RequestState, SemesterSteps, lastschrift_reference, n_, unwrap, )
from cdedb.frontend.cde_base import CdEBaseFrontend
from cdedb.frontend.common import (
    REQUESTdata, access, calculate_db_logparams, calculate_loglinks,
    make_membership_fee_reference, make_postal_address, Worker, TransactionObserver,
)


class CdESemesterMixin(CdEBaseFrontend):
    @access("finance_admin")
    def show_semester(self, rs: RequestState) -> Response:
        """Show information."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        period_history = self.cdeproxy.get_period_history(rs)
        if self.cdeproxy.may_start_semester_bill(rs):
            current_period_step = SemesterSteps.billing
        elif self.cdeproxy.may_start_semester_ejection(rs):
            current_period_step = SemesterSteps.ejection
        elif self.cdeproxy.may_start_semester_balance_update(rs):
            current_period_step = SemesterSteps.balance
        elif self.cdeproxy.may_advance_semester(rs):
            current_period_step = SemesterSteps.advance
        else:
            rs.notify("error", n_("Inconsistent semester state."))
            current_period_step = SemesterSteps.error
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        expuls_history = self.cdeproxy.get_expuls_history(rs)
        stats = self.cdeproxy.finance_statistics(rs)
        return self.render(rs, "semester/show_semester", {
            'period': period, 'expuls': expuls, 'stats': stats,
            'period_history': period_history, 'expuls_history': expuls_history,
            'current_period_step': current_period_step,
        })

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("addresscheck", "testrun")
    def semester_bill(self, rs: RequestState, addresscheck: bool, testrun: bool
                      ) -> Response:
        """Send billing mail to all members and archival notification to inactive users.

        In case of a test run we send a single mail of each to the button presser.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "cde/show_semester")
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_bill(rs):
            rs.notify("error", n_("Billing already done."))
            return self.redirect(rs, "cde/show_semester")
        open_lastschrift = self.determine_open_permits(rs)
        meta_info = self.coreproxy.get_meta_info(rs)

        if rs.has_validation_errors():
            return self.show_semester(rs)

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def send_billing_mail(rrs: RequestState, rs: None = None) -> bool:
            """Send one billing mail and advance semester state."""
            with TransactionObserver(rrs, self, "send_billing_mail"):
                proceed, persona = self.cdeproxy.process_for_semester_bill(
                    rrs, period_id, addresscheck, testrun)

                # Send mail only if transaction completed successfully.
                if persona:
                    lastschrift_list = self.cdeproxy.list_lastschrift(
                        rrs, persona_ids=(persona['id'],))
                    lastschrift = None
                    if lastschrift_list:
                        lastschrift = self.cdeproxy.get_lastschrift(
                            rrs, unwrap(lastschrift_list.keys()))
                        lastschrift['reference'] = lastschrift_reference(
                            persona['id'], lastschrift['id'])

                    address = make_postal_address(rrs, persona)
                    transaction_subject = make_membership_fee_reference(persona)
                    endangered = (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                                  and not persona['trial_member']
                                  and not lastschrift)
                    if endangered:
                        subject = "Mitgliedschaft verlängern"
                    else:
                        subject = "Mitgliedschaft verlängert"

                    self.do_mail(
                        rrs, "semester/billing",
                        {'To': (persona['username'],),
                         'Subject': subject},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'lastschrift': lastschrift,
                         'open_lastschrift': open_lastschrift,
                         'address': address,
                         'transaction_subject': transaction_subject,
                         'addresscheck': addresscheck,
                         'meta_info': meta_info})
            return proceed and not testrun

        def send_archival_notification(rrs: RequestState, rs: None = None) -> bool:
            """Send archival notifications to inactive accounts."""
            with TransactionObserver(rrs, self, "send_archival_notification"):
                proceed, persona = self.cdeproxy.process_for_semester_prearchival(
                    rrs, period_id, testrun)

                if persona:
                    self.do_mail(
                        rrs, "semester/imminent_archival",
                        {'To': (persona['username'],),
                         'Subject': "Bevorstehende Löschung Deines"
                                    " CdE-Datenbank-Accounts"},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'meta_info': meta_info})
            return proceed and not testrun

        Worker.create(
            rs, "semester_bill",
            (send_billing_mail, send_archival_notification), self.conf)
        rs.notify("success", n_("Started sending billing mails."))
        rs.notify("success", n_("Started sending archival notifications."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_eject(self, rs: RequestState) -> Response:
        """Eject members without enough credit and archive inactive users."""
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_ejection(rs):
            rs.notify("error", n_("Wrong timing for ejection."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def eject_member(rrs: RequestState, rs: None = None) -> bool:
            """Check one member for ejection and advance semester state."""
            with TransactionObserver(rrs, self, "eject_member"):
                proceed, persona = self.cdeproxy.process_for_semester_eject(
                    rrs, period_id)

                if persona:
                    transaction_subject = make_membership_fee_reference(persona)
                    meta_info = self.coreproxy.get_meta_info(rrs)
                    self.do_mail(
                        rrs, "semester/ejection",
                        {'To': (persona['username'],),
                         'Subject': "Austritt aus dem CdE e.V."},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'transaction_subject': transaction_subject,
                         'meta_info': meta_info})
            return proceed

        def automated_archival(rrs: RequestState, rs: None = None) -> bool:
            """Archive one inactive user if they are eligible."""
            with TransactionObserver(rrs, self, "automated_archival"):
                proceed, persona = self.cdeproxy.process_for_semester_archival(
                    rrs, period_id)

                if persona:
                    # TODO: somehow combine all failures into a single mail.
                    # This requires storing the ids somehow.
                    mail = self._create_mail(
                        text=f"Automated archival of persona {persona['id']} failed",
                        headers={'Subject': "Automated Archival failure",
                                 'To': (rrs.user.username,)},
                        attachments=None)
                    self._send_mail(mail)
            return proceed

        Worker.create(
            rs, "semester_eject", (eject_member, automated_archival), self.conf)
        rs.notify("success", n_("Started ejection."))
        rs.notify("success", n_("Started automated archival."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_balance_update(self, rs: RequestState) -> Response:
        """Deduct membership fees from all member accounts."""
        period_id = self.cdeproxy.current_period(rs)
        if not self.cdeproxy.may_start_semester_balance_update(rs):
            rs.notify("error", n_("Wrong timing for balance update."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def update_balance(rrs: RequestState, rs: None = None) -> bool:
            """Update one members balance and advance state."""
            proceed, persona = self.cdeproxy.process_for_semester_balance(
                rrs, period_id)
            return proceed

        Worker.create(rs, "semester_balance_update", update_balance, self.conf)
        rs.notify("success", n_("Started updating balance."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_advance(self, rs: RequestState) -> Response:
        """Proceed to next period."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        if not period['balance_done']:
            rs.notify("error", n_("Wrong timing for advancing the semester."))
            return self.redirect(rs, "cde/show_semester")
        self.cdeproxy.advance_semester(rs)
        rs.notify("success", n_("New period started."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("testrun", "skip")
    def expuls_addresscheck(self, rs: RequestState, testrun: bool, skip: bool
                            ) -> Response:
        """Send address check mail to all members.

        In case of a test run we send only a single mail to the button
        presser.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, 'cde/show_semester')

        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if expuls['addresscheck_done']:
            rs.notify("error", n_("Addresscheck already done."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def send_addresscheck(rrs: RequestState, rs: None = None) -> bool:
            """Send one address check mail and advance state."""
            with TransactionObserver(rrs, self, "send_addresscheck"):
                proceed, persona = self.cdeproxy.process_for_expuls_check(
                    rrs, expuls_id, testrun)
                if persona:
                    address = make_postal_address(rrs, persona)
                    self.do_mail(
                        rrs, "semester/addresscheck",
                        {'To': (persona['username'],),
                         'Subject': "Adressabfrage für den exPuls"},
                        {'persona': persona, 'address': address})
            return proceed and not testrun

        if skip:
            self.cdeproxy.finish_expuls_addresscheck(rs, skip=True)
            rs.notify("success", n_("Not sending mail."))
        else:
            Worker.create(rs, "expuls_addresscheck", send_addresscheck, self.conf)
            rs.notify("success", n_("Started sending mail."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def expuls_advance(self, rs: RequestState) -> Response:
        """Proceed to next expuls."""
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        if rs.has_validation_errors():
            return self.show_semester(rs)
        if not expuls['addresscheck_done']:
            rs.notify("error", n_("Addresscheck not done."))
            return self.redirect(rs, "cde/show_semester")
        self.cdeproxy.create_expuls(rs)
        rs.notify("success", n_("New expuls started."))
        return self.redirect(rs, "cde/show_semester")

    @access("cde_admin")
    @REQUESTdata(*LOG_FIELDS_COMMON)
    def view_cde_log(self, rs: RequestState,
                     codes: Collection[const.CdeLogCodes],
                     offset: Optional[int],
                     length: Optional[vtypes.PositiveInt],
                     persona_id: Optional[vtypes.CdedbID],
                     submitted_by: Optional[vtypes.CdedbID],
                     change_note: Optional[str],
                     time_start: Optional[datetime.datetime],
                     time_stop: Optional[datetime.datetime]) -> Response:
        """View general activity."""
        length = length or self.conf["DEFAULT_LOG_LENGTH"]
        # length is the requested length, _length the theoretically
        # shown length for an infinite amount of log entries.
        _offset, _length = calculate_db_logparams(offset, length)

        # no validation since the input stays valid, even if some options
        # are lost
        rs.ignore_validation_errors()
        total, log = self.cdeproxy.retrieve_cde_log(
            rs, codes, _offset, _length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)
        persona_ids = (
                {entry['submitted_by'] for entry in log if
                 entry['submitted_by']}
                | {entry['persona_id'] for entry in log if entry['persona_id']})
        personas = self.coreproxy.get_personas(rs, persona_ids)
        loglinks = calculate_loglinks(rs, total, offset, length)
        return self.render(rs, "semester/view_cde_log", {
            'log': log, 'total': total, 'length': _length,
            'personas': personas, 'loglinks': loglinks})
