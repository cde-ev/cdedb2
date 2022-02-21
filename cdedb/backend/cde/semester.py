#!/usr/bin/env python3

"""
The `CdESemesterBackend` subclasses the `CdEBaseBackend` and provides functionality
for the periodic semester management, with certain tasks that need to be performed on
individual members every semester.

For every step "foo" of semester management, there are the following methods:
  - `may_start_foo`
    - Returns `True` if it is the appropriate time to (re-)start this step.
  - `process_for_foo`
    - Apply the step for the given member.
  - `finish_foo`
    - Advance the semester to the next state so that further steps are allowed.
"""

from typing import Optional, Tuple

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.cde import CdELastschriftBackend
from cdedb.backend.common import access, affirm_validation as affirm
from cdedb.common import (
    EXPULS_PERIOD_FIELDS, ORG_PERIOD_FIELDS, ArchiveError, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, RequestState, n_, now, unwrap,
)
from cdedb.database.connection import Atomizer
from cdedb.filter import money_filter


class CdESemesterBackend(CdELastschriftBackend):
    @access("finance_admin")
    def finance_statistics(self, rs: RequestState) -> CdEDBObject:
        """Compute some financial statistics.

        Mostly for use by the 'Semesterverwaltung'.
        """
        with Atomizer(rs):
            query = ("SELECT COALESCE(SUM(balance), 0) as total,"
                     " COUNT(*) as count FROM core.personas "
                     " WHERE is_member = True AND balance < %s "
                     " AND trial_member = False")
            data = self.query_one(
                rs, query, (self.conf["MEMBERSHIP_FEE"],))
            ret = {
                'low_balance_members': data['count'] if data else 0,
                'low_balance_total': data['total'] if data else 0,
            }
            query = "SELECT COUNT(*) FROM core.personas WHERE is_member = True"
            ret['total_members'] = unwrap(self.query_one(rs, query, tuple()))
            query = ("SELECT COUNT(*) FROM core.personas"
                     " WHERE is_member = True AND trial_member = True")
            ret['trial_members'] = unwrap(self.query_one(rs, query, tuple()))
            query = ("SELECT COUNT(*) FROM core.personas AS p"
                     " JOIN cde.lastschrift AS l ON p.id = l.persona_id"
                     " WHERE p.is_member = True AND p.balance < %s"
                     " AND p.trial_member = False AND l.revoked_at IS NULL")
            ret['lastschrift_low_balance_members'] = unwrap(self.query_one(
                rs, query, (self.conf["MEMBERSHIP_FEE"],)))
        return ret

    @access("finance_admin")
    def get_period_history(self, rs: RequestState) -> CdEDBObjectMap:
        """Get the history of all org periods."""
        query = f"SELECT {', '.join(ORG_PERIOD_FIELDS)} FROM cde.org_period"
        return {e['id']: e for e in self.query_all(rs, query, tuple())}

    @access("cde")
    def get_period(self, rs: RequestState, period_id: int) -> CdEDBObject:
        """Get data for a semester."""
        period_id = affirm(vtypes.ID, period_id)
        ret = self.sql_select_one(rs, "cde.org_period", ORG_PERIOD_FIELDS,
                                  period_id)
        if not ret:
            raise ValueError(n_("This period does not exist."))
        ret["semester_start"] = unwrap(self.sql_select_one(
            rs, "cde.org_period", ("semester_done",), period_id - 1))
        return ret

    @access("finance_admin")
    def set_period(self, rs: RequestState,
                   period: CdEDBObject) -> DefaultReturnCode:
        """Set data for the current semester."""
        period = affirm(vtypes.Period, period)
        with Atomizer(rs):
            current_id = self.current_period(rs)
            if period['id'] != current_id:
                raise RuntimeError(n_("Only able to modify current period."))
            return self.sql_update(rs, "cde.org_period", period)

    @access("finance_admin")
    def may_advance_semester(self, rs: RequestState) -> bool:
        """Helper to determine if now is the right time to advance the semester.

        :returns: True if the semester may be advanced, False otherwise.
        """
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
        # Take special care about all previous steps.
        return all(period[key] for key in
                   ('billing_done', 'archival_notification_done', 'ejection_done',
                    'archival_done', 'balance_done'))

    @access("finance_admin")
    def advance_semester(self, rs: RequestState) -> DefaultReturnCode:
        """Mark  the current semester as finished and create a new semester."""
        with Atomizer(rs):
            current_id = self.current_period(rs)
            if not self.may_advance_semester(rs):
                raise RuntimeError(n_("Current period not finalized."))
            update = {
                'id': current_id,
                'semester_done': now(),
            }
            ret = self.sql_update(rs, "cde.org_period", update)
            new_period = {'id': current_id + 1}
            ret *= self.sql_insert(rs, "cde.org_period", new_period)
            self.cde_log(rs, const.CdeLogCodes.semester_advance,
                         persona_id=None, change_note=str(ret))
        return ret

    @access("finance_admin")
    def may_start_semester_bill(self, rs: RequestState) -> bool:
        """Helper to determine if now is the right time to start/resume billing.

        Beware that this step also involves the sending of archival notifications, so
        we check both.

        :returns: True if billing may be started, False otherwise.
        """
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
        # Both parts of the previous step need to be finished.
        return not (period['billing_done'] and period['archival_notification_done'])

    @access("finance_admin")
    def finish_semester_bill(self, rs: RequestState,
                             addresscheck: bool = False) -> DefaultReturnCode:
        """Conclude the semester bill step."""
        addresscheck = affirm(bool, addresscheck)
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
            if period['balance_done'] is not None:
                raise RuntimeError(n_("Billing already done for this period."))
            period_update = {
                'id': period_id,
                'billing_state': None,
                'billing_done': now(),
            }
            ret = self.set_period(rs, period_update)
            msg = f"{period['billing_count']} E-Mails versandt."
            if addresscheck:
                self.cde_log(
                    rs, const.CdeLogCodes.semester_bill_with_addresscheck,
                    persona_id=None, change_note=msg)
            else:
                self.cde_log(
                    rs, const.CdeLogCodes.semester_bill,
                    persona_id=None, change_note=msg)
        return ret

    @access("finance_admin")
    def finish_archival_notification(self, rs: RequestState) -> DefaultReturnCode:
        """Conclude the sending of archival notifications."""
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
            if period['archival_notification_done'] is not None:
                raise RuntimeError(n_("Archival notifications done for this period."))
            period_update = {
                'id': period_id,
                'archival_notification_state': None,
                'archival_notification_done': now(),
            }
            ret = self.set_period(rs, period_update)
            msg = f"{period['archival_notification_count']} E-Mails versandt."
            self.cde_log(
                rs, const.CdeLogCodes.automated_archival_notification_done,
                persona_id=None, change_note=msg)
        return ret

    @access("finance_admin")
    def may_start_semester_ejection(self, rs: RequestState) -> bool:
        """Helper to determine if now is the right time to start/resume ejection.

        Beware that this step also involves the automated archival, so we check both.

        :returns: True if ejection may be started, False otherwise.
        """
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
        return (period['billing_done'] and period['archival_notification_done']
                and not (period['ejection_done'] and period['archival_done']))

    @access("finance_admin")
    def finish_automated_archival(self, rs: RequestState) -> DefaultReturnCode:
        """Conclude the automated archival."""
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
            if not period['archival_notification_done']:
                raise RuntimeError(n_("Archival notifications not sent yet."))
            if period['archival_done'] is not None:
                raise RuntimeError(n_("Automated archival done for this period."))
            period_update = {
                'id': period_id,
                'archival_state': None,
                'archival_done': now(),
            }
            ret = self.set_period(rs, period_update)
            msg = f"{period['archival_count']} Accounts archiviert."
            self.cde_log(
                rs, const.CdeLogCodes.automated_archival_done,
                persona_id=None, change_note=msg)
        return ret

    @access("finance_admin")
    def finish_semester_ejection(self, rs: RequestState) -> DefaultReturnCode:
        """Conclude the semester ejection step."""
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
            if not period['billing_done']:
                raise RuntimeError(n_("Billing not done for this semester."))
            if period['ejection_done'] is not None:
                raise RuntimeError(n_("Ejection already done for this semester."))
            period_update = {
                'id': period_id,
                'ejection_state': None,
                'ejection_done': now(),
            }
            ret = self.set_period(rs, period_update)
            msg = f"{period['ejection_count']} inaktive Mitglieder gestrichen."
            msg += f" {period['ejection_balance']} € Guthaben eingezogen."
            self.cde_log(
                rs, const.CdeLogCodes.semester_ejection, persona_id=None,
                change_note=msg)
        return ret

    @access("finance_admin")
    def may_start_semester_balance_update(self, rs: RequestState) -> bool:
        """Helper to determine if now is the right time to start/resume balance update.

        :returns: True if the balance update may be started, False otherwise.
        """
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
        return (period['ejection_done'] and period['archival_done']
                and not period['balance_done'])

    @access("finance_admin")
    def finish_semester_balance_update(self, rs: RequestState) -> DefaultReturnCode:
        """Conclude the semester balance update step."""
        with Atomizer(rs):
            period_id = self.current_period(rs)
            period = self.get_period(rs, period_id)
            if not self.may_start_semester_balance_update(rs):
                raise RuntimeError(n_("Not the right time to finish balance update."))
            period_update = {
                'id': period_id,
                'balance_state': None,
                'balance_done': now(),
            }
            ret = self.set_period(rs, period_update)
            msg = "{} Probemitgliedschaften beendet. {} € Guthaben abgebucht."
            self.cde_log(
                rs, const.CdeLogCodes.semester_balance_update, persona_id=None,
                change_note=msg.format(period['balance_trialmembers'],
                                           period['balance_total']))
        return ret

    @access("finance_admin")
    def get_expuls_history(self, rs: RequestState) -> CdEDBObjectMap:
        """Get the history of all expuls semesters."""
        q = f"SELECT {', '.join(EXPULS_PERIOD_FIELDS)} FROM cde.expuls_period"
        return {e['id']: e for e in self.query_all(rs, q, tuple())}

    @access("cde")
    def current_expuls(self, rs: RequestState) -> int:
        """Check for the current expuls number."""
        query = "SELECT MAX(id) FROM cde.expuls_period"
        ret = unwrap(self.query_one(rs, query, tuple()))
        if not ret:
            raise ValueError(n_("No exPuls exists."))
        return ret

    @access("cde")
    def get_expuls(self, rs: RequestState, expuls_id: int) -> CdEDBObject:
        """Get data for the an expuls."""
        expuls_id = affirm(vtypes.ID, expuls_id)
        ret = self.sql_select_one(rs, "cde.expuls_period",
                                  EXPULS_PERIOD_FIELDS, expuls_id)
        if not ret:
            raise ValueError(n_("This exPuls does not exist."))
        return ret

    @access("finance_admin")
    def set_expuls(self, rs: RequestState,
                   expuls: CdEDBObject) -> DefaultReturnCode:
        """Set data for the an expuls."""
        expuls = affirm(vtypes.ExPuls, expuls)
        with Atomizer(rs):
            current_id = self.current_expuls(rs)
            if expuls['id'] != current_id:
                raise RuntimeError(n_("Only able to modify current expuls."))
            return self.sql_update(rs, "cde.expuls_period", expuls)

    @access("finance_admin")
    def create_expuls(self, rs: RequestState) -> DefaultReturnCode:
        """Mark the current expuls as finished and create a new expuls."""
        with Atomizer(rs):
            current_id = self.current_expuls(rs)
            current = self.get_expuls(rs, current_id)
            if not current['addresscheck_done']:
                raise RuntimeError(n_("Current expuls not finalized."))
            update = {
                'id': current_id,
                'expuls_done': now(),
            }
            ret = self.sql_update(rs, "cde.expuls_period", update)
            new_expuls = {
                'id': current_id + 1,
                'addresscheck_state': None,
                'addresscheck_done': None,
                'addresscheck_count': 0,
                'expuls_done': None,
            }
            ret *= self.sql_insert(rs, "cde.expuls_period", new_expuls)
            self.cde_log(rs, const.CdeLogCodes.expuls_advance,
                         persona_id=None, change_note=str(ret))
        return ret

    @access("finance_admin")
    def finish_expuls_addresscheck(self, rs: RequestState,
                                   skip: bool = False) -> DefaultReturnCode:
        """Conclude the expuls addresscheck step."""
        skip = affirm(bool, skip)
        with Atomizer(rs):
            expuls_id = self.current_expuls(rs)
            expuls = self.get_expuls(rs, expuls_id)
            if not expuls['addresscheck_done'] is None:
                raise RuntimeError(n_(
                    "Addresscheck already done for this expuls."))
            expuls_update = {
                'id': expuls_id,
                'addresscheck_state': None,
                'addresscheck_done': now(),
            }
            ret = self.set_expuls(rs, expuls_update)
            msg = f"{expuls['addresscheck_count']} E-Mails versandt."
            if skip:
                self.cde_log(rs, const.CdeLogCodes.expuls_addresscheck_skipped,
                             persona_id=None, change_note=msg)
            else:
                self.cde_log(rs, const.CdeLogCodes.expuls_addresscheck,
                             persona_id=None, change_note=msg)
        return ret

    @access("finance_admin")
    def process_for_semester_bill(self, rs: RequestState, period_id: int,
                                  addresscheck: bool, testrun: bool
                                  ) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to bill one persona.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            work was performed on this invocation.
        """
        period_id = affirm(int, period_id)
        addresscheck = affirm(bool, addresscheck)
        testrun = affirm(bool, testrun)
        with Atomizer(rs):
            period = self.get_period(rs, period_id)
            persona_id = self.core.next_persona(
                rs, period['billing_state'], is_member=True, is_archived=False)
            if testrun:
                persona_id = rs.user.persona_id
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or period['billing_done']:
                if not period['billing_done']:
                    self.finish_semester_bill(rs, addresscheck)
                return False, None
            period_update = {
                'id': period_id,
                'billing_state': persona_id,
            }
            persona = self.core.get_cde_user(rs, persona_id)
            period_update['billing_count'] = period['billing_count'] + 1
            if not testrun:
                self.set_period(rs, period_update)

            return True, persona

    @access("finance_admin")
    def process_for_semester_prearchival(self, rs: RequestState, period_id: int,
                                         testrun: bool
                                         ) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to warn one persona prior to archival.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            work was performed on this invocation.
        """
        period_id = affirm(int, period_id)
        testrun = affirm(bool, testrun)
        with Atomizer(rs):
            period = self.get_period(rs, period_id)
            persona_id = self.core.next_persona(
                rs, period['archival_notification_state'], is_member=None,
                is_archived=False)
            if testrun:
                persona_id = rs.user.persona_id
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or period['archival_notification_done']:
                if not period['archival_notification_done']:
                    self.finish_archival_notification(rs)
                return False, None
            period_update = {
                'id': period_id,
                'archival_notification_state': persona_id,
            }
            is_archivable = self.core.is_persona_automatically_archivable(
                rs, persona_id)
            persona = None
            if is_archivable or testrun:
                persona = self.core.get_persona(rs, persona_id)
                period_update['archival_notification_count'] = \
                    period['archival_notification_count'] + 1
            if not testrun:
                self.set_period(rs, period_update)
            return True, persona

    @access("finance_admin")
    def process_for_semester_eject(self, rs: RequestState, period_id: int,
                                   ) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to eject one (soon to be ex-)member.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            work was performed on this invocation.
        """
        period_id = affirm(int, period_id)
        with Atomizer(rs):
            period = self.get_period(rs, period_id)
            persona_id = self.core.next_persona(
                rs, period['ejection_state'], is_member=True, is_archived=False)
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or period['ejection_done']:
                if not period['ejection_done']:
                    self.finish_semester_ejection(rs)
                return False, None
            period_update = {
                'id': period_id,
                'ejection_state': persona_id,
            }
            persona = self.core.get_cde_user(rs, persona_id)
            do_eject = (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                        and not persona['trial_member'])
            if do_eject:
                self.change_membership(rs, persona_id, is_member=False)
                period_update['ejection_count'] = \
                    period['ejection_count'] + 1
                period_update['ejection_balance'] = \
                    period['ejection_balance'] + persona['balance']
            else:
                persona = None  # type: ignore[assignment]
            self.set_period(rs, period_update)
            return True, persona

    @access("finance_admin")
    def process_for_semester_archival(self, rs: RequestState, period_id: int,
                                      ) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to archive one persona.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            an error occured during archival (deviating from the common
            pattern for this functions which return a persona if work was
            performed on this invocation).
        """
        period_id = affirm(int, period_id)
        with Atomizer(rs):
            period = self.get_period(rs, period_id)
            persona_id = self.core.next_persona(
                rs, period['archival_state'], is_member=False, is_archived=False)
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or period['archival_done']:
                if not period['archival_done']:
                    self.finish_automated_archival(rs)
                return False, None
            period_update = {
                'id': period_id,
                'archival_state': persona_id,
            }
            persona = None
            if self.core.is_persona_automatically_archivable(
                    rs, persona_id, reference_date=period['billing_done']):
                note = "Autmoatisch archiviert wegen Inaktivität."
                try:
                    code = self.core.archive_persona(rs, persona_id, note)
                except ArchiveError:
                    self.logger.exception(f"Unexpected error during archival of"
                                          f" persona {persona_id}.")
                    persona = {'persona_id': persona_id}
                else:
                    if code:
                        period_update['archival_count'] = \
                            period['archival_count'] + 1
                    else:
                        self.logger.error(
                            f"Automated archival of persona {persona_id} failed"
                            f" for unknown reasons.")
                        persona = {'id': persona_id}
            self.set_period(rs, period_update)
            return True, persona

    @access("finance_admin")
    def process_for_semester_balance(self, rs: RequestState, period_id: int,
                                     ) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to update the balance of one member.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            work was performed on this invocation.
        """
        period_id = affirm(int, period_id)
        with Atomizer(rs):
            period = self.get_period(rs, period_id)
            persona_id = self.core.next_persona(
                rs, period['balance_state'], is_member=True, is_archived=False)
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or period['balance_done']:
                if not period['balance_done']:
                    self.finish_semester_balance_update(rs)
                return False, None
            persona = self.core.get_cde_user(rs, persona_id)
            period_update = {
                'id': period_id,
                'balance_state': persona_id,
            }
            if (persona['balance'] < self.conf["MEMBERSHIP_FEE"]
                    and not persona['trial_member']):
                # TODO maybe fail more gracefully here?
                # Maybe set balance to 0 and send a mail or something.
                raise ValueError(n_("Balance too low."))
            else:
                if persona['trial_member']:
                    update = {
                        'id': persona_id,
                        'trial_member': False,
                    }
                    self.core.change_persona(
                        rs, update,
                        change_note="Probemitgliedschaft beendet."
                    )
                    period_update['balance_trialmembers'] = \
                        period['balance_trialmembers'] + 1
                else:
                    new_b = persona['balance'] - self.conf["MEMBERSHIP_FEE"]
                    note = "Mitgliedsbeitrag abgebucht ({}).".format(
                        money_filter(self.conf["MEMBERSHIP_FEE"]))
                    self.core.change_persona_balance(
                        rs, persona_id, new_b,
                        const.FinanceLogCodes.deduct_membership_fee,
                        change_note=note)
                    new_total = (period['balance_total']
                                 + self.conf["MEMBERSHIP_FEE"])
                    period_update['balance_total'] = new_total
            self.set_period(rs, period_update)
            return True, persona

    @access("finance_admin")
    def process_for_expuls_check(self, rs: RequestState, expuls_id: int,
                                 testrun: bool) -> Tuple[bool, Optional[CdEDBObject]]:
        """Atomized call to initiate addres check.

        :returns: A tuple consisting of a boolean signalling whether there
            is more work to do and an optional persona which is present if
            work was performed on this invocation.
        """
        expuls_id = affirm(int, expuls_id)
        testrun = affirm(bool, testrun)
        with Atomizer(rs):
            expuls = self.get_expuls(rs, expuls_id)
            persona_id = self.core.next_persona(
                rs, expuls['addresscheck_state'],
                is_member=True, is_archived=False)
            if testrun:
                persona_id = rs.user.persona_id
            # We are finished if we reached the end or if this was previously done.
            if not persona_id or expuls['addresscheck_done']:
                if not expuls['addresscheck_done']:
                    self.finish_expuls_addresscheck(
                        rs, skip=False)
                return False, None
            persona = self.core.get_cde_user(rs, persona_id)
            if not testrun:
                expuls_update = {
                    'id': expuls_id,
                    'addresscheck_state': persona_id,
                    'addresscheck_count': expuls['addresscheck_count'] + 1,
                }
                self.set_expuls(rs, expuls_update)
            return True, persona
