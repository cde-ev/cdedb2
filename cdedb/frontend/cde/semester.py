#!/usr/bin/env python3

"""Semester management services for the cde realm.

Everything here requires the "finance_admin" role, except viewing the semester log,
which requires "cde_admin". Note that every "finance_admin" is also a "cde_admin".
"""

from werkzeug import Response

import cdedb.database.constants as const
from cdedb.common import CdEDBObject, RequestState, lastschrift_reference, unwrap
from cdedb.common.n_ import n_
from cdedb.common.query.log_filter import CdELogFilter
from cdedb.frontend.cde.base import CdEBaseFrontend
from cdedb.frontend.common import (
    REQUESTdata,
    REQUESTdatadict,
    TransactionObserver,
    Worker,
    access,
    make_membership_fee_reference,
    make_postal_address,
)


class CdESemesterMixin(CdEBaseFrontend):
    @access("cde_admin")
    def show_semester(self, rs: RequestState) -> Response:
        """Show information."""
        period_id = self.cdeproxy.current_period(rs)
        period = self.cdeproxy.get_period(rs, period_id)
        period_history = self.cdeproxy.get_period_history(rs)
        allowed_semester_steps = self.cdeproxy.allowed_semester_steps(rs)
        # group all allowed steps into the three steps we display to the user
        in_step_1 = (allowed_semester_steps.advance or allowed_semester_steps.billing
                     or allowed_semester_steps.archival_notification)
        in_step_2 = (allowed_semester_steps.exmember_balance
                     or allowed_semester_steps.ejection
                     or allowed_semester_steps.automated_archival)
        in_step_3 = allowed_semester_steps.balance
        during_step_1 = (period["billing_state"]
                         or period["archival_notification_state"])
        # here, we cheat a bit to display two separate backend steps as one
        during_step_2 = (period['exmember_state']
                         or period['ejection_state']
                         or period['archival_state']
                         or allowed_semester_steps.ejection
                         or allowed_semester_steps.automated_archival)
        during_step_3 = period['balance_state']
        expuls_id = self.cdeproxy.current_expuls(rs)
        expuls = self.cdeproxy.get_expuls(rs, expuls_id)
        expuls_history = self.cdeproxy.get_expuls_history(rs)
        stats = self.cdeproxy.finance_statistics(rs)
        return self.render(rs, "semester/show_semester", {
            'period': period, 'expuls': expuls, 'stats': stats,
            'period_history': period_history, 'expuls_history': expuls_history,
            'in_step_1': in_step_1, 'in_step_2': in_step_2, 'in_step_3': in_step_3,
            'during_step_1': during_step_1, 'during_step_2': during_step_2,
            'during_step_3': during_step_3,
        })

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("addresscheck", "testrun")
    def semester_bill(self, rs: RequestState, addresscheck: bool, testrun: bool,
                      ) -> Response:
        """Send billing mail to all members and archival notification to inactive users.

        In case of a test run we send a single mail of each to the button presser.
        As a side effect, this also advances the cde_period.

        It may happen that the Worker sending the mails crashs. Then, calling this
        function will start a new worker, but take the latest state of the old worker
        into account, so mails will not be sent twice.
        """
        if rs.has_validation_errors():
            return self.redirect(rs, "cde/show_semester")

        # advance to the next semester
        # This does not throw an error if we may not advance, since the function must
        #  be idempotent if the sending crushes midway.
        if self.cdeproxy.allowed_semester_steps(rs).advance:
            self.cdeproxy.advance_semester(rs)

        period_id = self.cdeproxy.current_period(rs)
        allowed_steps = self.cdeproxy.allowed_semester_steps(rs)
        if not (allowed_steps.billing or allowed_steps.archival_notification):
            rs.notify("error", n_("Billing already done."))
            return self.redirect(rs, "cde/show_semester")
        open_lastschrift = self.determine_open_permits(rs)
        meta_info = self.coreproxy.get_meta_info(rs)
        annual_fee = self.cdeproxy.annual_membership_fee(rs)

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
                    endangered = (
                            persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                            and not persona['trial_member']
                            and not persona['honorary_member']
                            and not lastschrift
                    )
                    if endangered:
                        subject = "Deine Mitgliedschaft läuft aus"
                    else:
                        subject = "Deine Mitgliedschaft wird verlängert"

                    self.do_mail(
                        rrs, "semester/billing",
                        {'To': (persona['username'],),
                         'Subject': subject},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'annual_fee': annual_fee,
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
                    transaction_subject = make_membership_fee_reference(persona)
                    self.do_mail(
                        rrs, "semester/imminent_archival",
                        {'To': (persona['username'],),
                         'Subject': "Bevorstehende Löschung Deines"
                                    " CdE-Datenbank-Accounts"},
                        {'persona': persona,
                         'fee': self.conf["MEMBERSHIP_FEE"],
                         'transaction_subject': transaction_subject,
                         'meta_info': meta_info})
            return proceed and not testrun

        Worker.create(
            rs, "semester_bill",
            (send_billing_mail, send_archival_notification), self.conf)
        if allowed_steps.billing:
            rs.notify("success", n_("Started sending billing mails."))
        if allowed_steps.archival_notification:
            rs.notify("success", n_("Started sending archival notifications."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_eject(self, rs: RequestState) -> Response:
        """Eject members without enough credit and archive inactive users.

        Immediately before the ejection, remove the remaining balance of all exmembers.

        It may happen that the Worker crashs. Then, calling this function will start a
        new worker, but take the latest state of the old worker into account.
        """
        if rs.has_validation_errors():  # pragma: no cover
            self.redirect(rs, "cde/show_semester")
        period_id = self.cdeproxy.current_period(rs)
        allowed_steps = self.cdeproxy.allowed_semester_steps(rs)
        if not (allowed_steps.exmember_balance or allowed_steps.ejection
                or allowed_steps.automated_archival):
            rs.notify("error", n_("Wrong timing for ejection."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def update_exmember_balance(rrs: RequestState, rs: None = None) -> bool:
            """Update one exmembers balance and advance state."""
            proceed, _ = self.cdeproxy.process_for_exmember_balance(
                rrs, period_id)
            return proceed

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
                    defect_addresses = self.coreproxy.list_email_states(
                        rrs, const.EmailStatus.defect_states())
                    mail = self._create_mail(
                        text=f"Automated archival of persona {persona['id']} failed",
                        headers={'Subject': "Automated Archival failure",
                                 'To': (rrs.user.username,)},
                        attachments=None, defect_addresses=defect_addresses)
                    self._send_mail(mail)
            return proceed

        if allowed_steps.exmember_balance:
            rs.notify("success", n_("Started updating exmember balance."))
        if allowed_steps.ejection:
            rs.notify("success", n_("Started ejection."))
        if allowed_steps.automated_archival:
            rs.notify("success", n_("Started automated archival."))
        Worker.create(
            rs, "semester_eject",
            (update_exmember_balance, eject_member, automated_archival), self.conf)
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    def semester_balance_update(self, rs: RequestState) -> Response:
        """Deduct membership fees from all member accounts.

        It may happen that the Worker crashs. Then, calling this function will start a
        new worker, but take the latest state of the old worker into account.
        """
        if rs.has_validation_errors():  # pragma: no cover
            self.redirect(rs, "cde/show_semester")
        period_id = self.cdeproxy.current_period(rs)
        allowed_steps = self.cdeproxy.allowed_semester_steps(rs)
        if not allowed_steps.balance:
            rs.notify("error", n_("Wrong timing for balance update."))
            return self.redirect(rs, "cde/show_semester")

        # The rs parameter shadows the outer request state, making sure that
        # it doesn't leak
        def update_balance(rrs: RequestState, rs: None = None) -> bool:
            """Update one members balance and advance state."""
            proceed, _ = self.cdeproxy.process_for_semester_balance(
                rrs, period_id)
            return proceed

        Worker.create(rs, "semester_balance_update", (update_balance,), self.conf)
        rs.notify("success", n_("Started updating balance."))
        return self.redirect(rs, "cde/show_semester")

    @access("finance_admin", modi={"POST"})
    @REQUESTdata("testrun", "skip")
    def expuls_addresscheck(self, rs: RequestState, testrun: bool, skip: bool,
                            ) -> Response:
        """Send address check mail to all members who receive a printed exPuls.

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
        if rs.has_validation_errors():  # pragma: no cover
            return self.show_semester(rs)
        if not expuls['addresscheck_done']:
            rs.notify("error", n_("Addresscheck not done."))
            return self.redirect(rs, "cde/show_semester")
        self.cdeproxy.create_expuls(rs)
        rs.notify("success", n_("New expuls started."))
        return self.redirect(rs, "cde/show_semester")

    @REQUESTdatadict(*CdELogFilter.requestdict_fields())
    @REQUESTdata("download")
    @access("cde_admin", "auditor")
    def view_cde_log(self, rs: RequestState, data: CdEDBObject, download: bool,
                     ) -> Response:
        """View semester activity."""
        return self.generic_view_log(
            rs, data, CdELogFilter, self.cdeproxy.retrieve_cde_log,
            download=download, template="semester/view_cde_log",
        )
