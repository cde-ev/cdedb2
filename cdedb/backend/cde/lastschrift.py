#!/usr/bin/env python3

"""
The `CdELastschriftBackend` subclasses the `CdEBaseBackend` and provides funcitonality
for managing SEPA permits (called by their german name "Lastschrift") and SEPA
transactions.
"""

import datetime
import decimal
from typing import Any, Collection, Dict, List, Optional, Protocol, Tuple

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.cde import CdEBaseBackend
from cdedb.backend.common import (
    access, affirm_array_validation as affirm_array,
    affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, batchify, singularize,
)
from cdedb.common import (
    CdEDBObject, CdEDBObjectMap, DefaultReturnCode, DeletionBlockers, RequestState,
    merge_dicts, now, unwrap,
)
from cdedb.common.exceptions import PrivilegeError
from cdedb.common.fields import LASTSCHRIFT_FIELDS, LASTSCHRIFT_TRANSACTION_FIELDS
from cdedb.common.n_ import n_
from cdedb.database.connection import Atomizer


class CdELastschriftBackend(CdEBaseBackend):
    @access("core_admin", "cde_admin")
    def change_membership(
            self, rs: RequestState, persona_id: int, is_member: bool
    ) -> Tuple[DefaultReturnCode, Optional[int], bool]:
        """Special modification function for membership.

        This is similar to the version from the core backend, but can
        additionally handle lastschrift permits.

        In the general situation this variant should be used.

        :param is_member: Desired target state of membership.
        :returns: A tuple containing the return code, the id of the
            revoked lastschrift permit or None, and whether any in-flight
            transactions are affected.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        is_member = affirm(bool, is_member)
        code = 1
        revoked_permit = None
        collateral_transactions = False
        with Atomizer(rs):
            if not is_member:
                lastschrift_ids = self.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=True)
                # at most one active lastschrift per user is allowed
                if lastschrift_id := unwrap(lastschrift_ids or None):
                    if self.list_lastschrift_transactions(
                            rs, lastschrift_ids=(lastschrift_id,),
                            stati=(const.LastschriftTransactionStati.issued,)):
                        collateral_transactions = True
                    data = {
                        'id': lastschrift_id,
                        'revoked_at': now(),
                    }
                    lastschrift_code = self.set_lastschrift(rs, data)
                    if lastschrift_code <= 0:
                        raise ValueError(n_(
                            "Failed to revoke active lastschrift permit"))
                    revoked_permit = lastschrift_id
            code = self.core.change_membership_easy_mode(rs, persona_id, is_member)
        return code, revoked_permit, collateral_transactions

    @access("member", "core_admin", "cde_admin")
    def list_lastschrift(self, rs: RequestState,
                         persona_ids: Collection[int] = None,
                         active: Optional[bool] = True) -> Dict[int, int]:
        """List all direct debit permits.

        :returns: Mapping of lastschrift_ids to their respecive persona_ids.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids or set())
        if (not ({"cde_admin", "core_admin"} & rs.user.roles)
            and (not persona_ids
                 or any(p_id != rs.user.persona_id for p_id in persona_ids))):
            raise PrivilegeError(n_("Not privileged."))
        active = affirm_optional(bool, active)
        query = "SELECT id, persona_id FROM cde.lastschrift"
        params = []
        constraints = []
        if persona_ids:
            constraints.append("persona_id = ANY(%s)")
            params.append(persona_ids)
        if active is not None:
            constraints.append("revoked_at {} NULL".format(
                "IS" if active else "IS NOT"))
        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("member", "cde_admin")
    def get_lastschrifts(self, rs: RequestState, lastschrift_ids: Collection[int]
                         ) -> CdEDBObjectMap:
        """Retrieve direct debit permits."""
        lastschrift_ids = affirm_set(vtypes.ID, lastschrift_ids)
        data = self.sql_select(
            rs, "cde.lastschrift", LASTSCHRIFT_FIELDS, lastschrift_ids)
        if ("cde_admin" not in rs.user.roles
                and any(e['persona_id'] != rs.user.persona_id for e in data)):
            raise PrivilegeError(n_("Not privileged."))
        return {e['id']: e for e in data}

    class _GetLastschriftProtocol(Protocol):
        def __call__(self, rs: RequestState, lastschrift_id: int) -> CdEDBObject: ...
    get_lastschrift: _GetLastschriftProtocol = singularize(
        get_lastschrifts, "lastschrift_ids", "lastschrift_id")

    @access("cde_admin")
    def set_lastschrift(self, rs: RequestState,
                        data: CdEDBObject) -> DefaultReturnCode:
        """Modify a direct debit permit."""
        data = affirm(vtypes.Lastschrift, data)
        with Atomizer(rs):
            # First check whether we revoke a lastschrift
            log_code = const.FinanceLogCodes.modify_lastschrift
            if data.get('revoked_at'):
                current = unwrap(self.sql_select_one(
                    rs, "cde.lastschrift", ("revoked_at",), data['id']))
                if not current:
                    log_code = const.FinanceLogCodes.revoke_lastschrift
            # Now make the change
            ret = self.sql_update(rs, "cde.lastschrift", data)
            persona_id = unwrap(self.sql_select_one(
                rs, "cde.lastschrift", ("persona_id",), data['id']))
            self.core.finance_log(rs, log_code, persona_id, None, None)
        return ret

    @access("finance_admin")
    def create_lastschrift(self, rs: RequestState, data: CdEDBObject,
                           initial_donation: decimal.Decimal
    ) -> DefaultReturnCode:
        """Make a new direct debit permit."""
        data = affirm(vtypes.Lastschrift, data, creation=True)
        initial_donation = affirm(vtypes.PositiveDecimal, initial_donation)
        data['submitted_by'] = rs.user.persona_id
        with Atomizer(rs):
            if self.list_lastschrift(rs, persona_ids=(data['persona_id'],),
                                     active=True):
                raise ValueError(n_("Multiple active permits are disallowed."))
            new_id = self.sql_insert(rs, "cde.lastschrift", data)
            self.core.finance_log(rs, const.FinanceLogCodes.grant_lastschrift,
                                  data['persona_id'], None, None)
            if not self.core.verify_persona(rs, data["persona_id"], ["cde"]):
                raise ValueError(n_("Invalid persona."))
            update = {"id": data["persona_id"], "donation": initial_donation}
            msg = "Setzen einer initialen Spende nach Lastschrifterstellung."
            self.core.change_persona(rs, update, change_note=msg)
        return new_id

    @access("finance_admin")
    def delete_lastschrift_blockers(self, rs: RequestState, lastschrift_id: int
                                    ) -> DeletionBlockers:
        """Determine what keeps a lastschrift from being revoked.

        Possible blockers:

        * 'revoked_at': Deletion is only possible 18 months after revoking.
        * 'transactions': Transactions that were issued for this lastschrift.
        * 'active_transactions': Cannot delete a lastschrift that still has
            open transactions.
        """
        lastschrift_id = affirm(vtypes.ID, lastschrift_id)
        blockers: CdEDBObject = {}

        with Atomizer(rs):
            lastschrift = self.get_lastschrift(rs, lastschrift_id)
            # SEPA mandates need to be kept for at least 14 months after the
            # last transaction. We want to be on the safe side, so we keep them
            # for at least 14 months after revokation, which should always be
            # after the last transaction.
            # See also: ("Wie sind SEPA-Mandate aufzubewahren?")
            # https://www.bundesbank.de/action/de/613964/bbksearch \
            # ?pageNumString=1#anchor-640260
            # We instead require 18 months to have passed just to be safe.
            if not lastschrift["revoked_at"] or now() < (
                    lastschrift["revoked_at"] + datetime.timedelta(days=18*30)):
                blockers["revoked_at"] = [lastschrift_id]

            transaction_ids = self.list_lastschrift_transactions(
                rs, lastschrift_ids=(lastschrift_id,))
            if transaction_ids:
                blockers["transactions"] = list(transaction_ids.keys())
                active_transactions = self.list_lastschrift_transactions(
                    rs, lastschrift_ids=(lastschrift_id,),
                    stati=(const.LastschriftTransactionStati.issued,))
                if active_transactions:
                    blockers["active_transactions"] = list(active_transactions)

        return blockers

    @access("finance_admin")
    def delete_lastschrift(self, rs: RequestState, lastschrift_id: int,
                           cascade: Collection[str] = None
                           ) -> DefaultReturnCode:
        """Remove data about an old lastschrift.

        Only possible after the lastschrift has been revoked for at least 18
        months.
        """
        lastschrift_id = affirm(vtypes.ID, lastschrift_id)
        cascade = affirm_set(str, cascade or [])

        ret = 1
        with Atomizer(rs):
            lastschrift = self.get_lastschrift(rs, lastschrift_id)
            blockers = self.delete_lastschrift_blockers(rs, lastschrift_id)
            cascade &= blockers.keys()
            if blockers.keys() - cascade:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {
                        "type": "lastschrift",
                        "block": blockers.keys() - cascade,
                    })
            if cascade:
                msg = n_("Unable to cascade %(blocker)s.")
                if "revoked_at" in blockers:
                    raise ValueError(msg, {"blocker": "revoked_at"})
                if "active_transactions" in blockers:
                    raise ValueError(msg, {"blocker": "active_transactions"})
                if "transactions" in blockers:
                    ret *= self.sql_delete(rs, "cde.lastschrift_transactions",
                                           blockers["transactions"])

                blockers = self.delete_lastschrift_blockers(rs, lastschrift_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "cde.lastschrift", lastschrift_id)
                self.core.finance_log(
                    rs, const.FinanceLogCodes.lastschrift_deleted,
                    persona_id=lastschrift["persona_id"], delta=None,
                    new_balance=None)
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "lastschrift", "block": blockers.keys()})
        return ret

    @access("member", "cde_admin")
    def list_lastschrift_transactions(
            self, rs: RequestState, lastschrift_ids: Collection[int] = None,
            stati: Collection[const.LastschriftTransactionStati] = None,
            periods: Collection[int] = None) -> Dict[int, int]:
        """List direct debit transactions.
        :param lastschrift_ids: If this is not None show only those
          transactions originating with ids in the list.
        :param stati: If this is not None show only transactions with these
          statuses.
        :param periods: If this is not None show only those transactions in
          the specified periods.
        :returns: Mapping of transaction ids to direct debit permit ids.
        """
        lastschrift_ids = affirm_set(vtypes.ID, lastschrift_ids or set())
        if "cde_admin" not in rs.user.roles:
            if lastschrift_ids is None:
                # Don't allow None for non-admins.
                raise PrivilegeError(n_("Not privileged."))
            else:
                # Otherwise pass this to get_lastschrift, which does access check.
                self.get_lastschrifts(rs, lastschrift_ids)
        stati = affirm_set(const.LastschriftTransactionStati, stati or set())
        periods = affirm_set(vtypes.ID, periods or set())
        query = "SELECT id, lastschrift_id FROM cde.lastschrift_transactions"
        params: List[Any] = []
        constraints = []
        if lastschrift_ids:
            constraints.append("lastschrift_id = ANY(%s)")
            params.append(lastschrift_ids)
        if stati:
            constraints.append("status = ANY(%s)")
            params.append(stati)
        if periods:
            constraints.append("period_id = ANY(%s)")
            params.append(periods)
        if constraints:
            query = query + " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)
        return {e['id']: e['lastschrift_id'] for e in data}

    @access("member", "finance_admin")
    def get_lastschrift_transactions(self, rs: RequestState,
                                     ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve direct debit transactions."""
        ids = affirm_set(vtypes.ID, ids)
        data = self.sql_select(rs, "cde.lastschrift_transactions",
                               LASTSCHRIFT_TRANSACTION_FIELDS, ids)
        # We only need these for access checking, which is done inside.
        self.get_lastschrifts(rs, {e["lastschrift_id"] for e in data})
        ret = {}
        for e in data:
            e['status'] = const.LastschriftTransactionStati(e['status'])
            ret[e['id']] = e
        return ret

    class _GetLastschriftTransactionProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> CdEDBObject: ...
    get_lastschrift_transaction: _GetLastschriftTransactionProtocol = singularize(
        get_lastschrift_transactions)

    @access("finance_admin")
    def annual_membership_fee(self, rs: RequestState) -> decimal.Decimal:
        """The (expected) annual membership fee.

        Care has to be taken if there is more than one period per year (currently two):
        If the fee changes between two periods of the same year, this function needs to
        be adjusted _in advance_ to reflect this change, so the right amount of money
        can be issued as lastschrift transaction.
        """
        return self.conf["PERIODS_PER_YEAR"] * self.conf["MEMBERSHIP_FEE"]

    @access("finance_admin")
    def transaction_amount(self, rs: RequestState, persona_id: int) -> decimal.Decimal:
        """The amount of a lastschrift transaction."""
        persona_id = affirm(vtypes.ID, persona_id)
        user = self.core.get_cde_user(rs, persona_id)
        return user["donation"] + self.annual_membership_fee(rs)

    @access("finance_admin")
    def issue_lastschrift_transaction(self, rs: RequestState, lastschrift_id: int,
                                      ) -> DefaultReturnCode:
        """Make a new direct debit transaction.

        This only creates the database entry. The SEPA file will be
        generated in the frontend.

        :returns: The id of the new transaction.
        """
        stati = const.LastschriftTransactionStati
        lastschrift_id = affirm(vtypes.ID, lastschrift_id)
        with Atomizer(rs):
            lastschrift = self.get_lastschrift(rs, lastschrift_id)
            if lastschrift['revoked_at']:
                raise RuntimeError(n_("Lastschrift already revoked."))
            period = self.current_period(rs)
            # TODO maybe check that there is no successful transaction
            transaction_ids = self.list_lastschrift_transactions(
                rs, lastschrift_ids=(lastschrift_id,),
                periods=(period,), stati=(stati.issued,))
            if transaction_ids:
                raise RuntimeError(n_("Existing pending transaction."))
            data = {
                'issued_at': now(),
                'processed_at': None,
                'tally': None,
                'submitted_by': rs.user.persona_id,
                'period_id': period,
                'status': stati.issued,
                'amount': self.transaction_amount(rs, lastschrift["persona_id"])
            }
            ret = self.sql_insert(rs, "cde.lastschrift_transactions", data)
            self.core.finance_log(
                rs, const.FinanceLogCodes.lastschrift_transaction_issue,
                lastschrift['persona_id'], None, None,
                change_note=data['amount'])
        return ret
    issue_lastschrift_transaction_batch = batchify(
        issue_lastschrift_transaction)

    @access("finance_admin")
    def finalize_lastschrift_transaction(
            self, rs: RequestState, transaction_id: int,
            status: const.LastschriftTransactionStati) -> DefaultReturnCode:
        """Tally a direct debit transaction.

        That is either book the successful transaction, book the fees for a
        failure or cancel the transaction alltogether.

        :param status: If this is ``failed`` the direct debit permit is revoked
          so that no further transactions are issued for it.
        :param tally: The actual amount of money that was moved. This may be
          negative if we incur fees for failed transactions. In case of
          success the balance of the persona is increased by the yearly
          membership fee.
        """
        transaction_id = affirm(vtypes.ID, transaction_id)
        status = affirm(const.LastschriftTransactionStati, status)
        if not status.is_finalized():
            raise RuntimeError(n_("Non-final target state."))
        with Atomizer(rs):
            transaction = self.get_lastschrift_transaction(rs, transaction_id)
            if transaction['status'].is_finalized():
                raise RuntimeError(n_("Transaction already tallied."))
            if status == const.LastschriftTransactionStati.success:
                tally = transaction['amount']
            elif status == const.LastschriftTransactionStati.cancelled:
                tally = decimal.Decimal(0)
            elif status == const.LastschriftTransactionStati.failure:
                tally = -self.conf["SEPA_ROLLBACK_FEE"]
            else:
                raise RuntimeError(n_("Impossible"))
            update = {
                'id': transaction_id,
                'processed_at': now(),
                'tally': tally,
                'status': status,
            }
            ret = self.sql_update(rs, "cde.lastschrift_transactions", update)
            lastschrift = self.get_lastschrift(rs, transaction['lastschrift_id'])
            persona_id = lastschrift['persona_id']
            delta = None
            new_balance = None
            if status == const.LastschriftTransactionStati.success:
                code = const.FinanceLogCodes.lastschrift_transaction_success
                user = self.core.get_cde_user(rs, persona_id)
                delta = self.annual_membership_fee(rs)
                new_balance = user['balance'] + delta
                ret *= self.core.change_persona_balance(
                    rs, persona_id, new_balance, code,
                    change_note="Erfolgreicher Lastschrifteinzug.")
                # We provide membership directly after the successful transaction.
                self.change_membership(rs, persona_id, is_member=True)
                # Return early since change_persona_balance does the logging
                return ret
            elif status == const.LastschriftTransactionStati.failure:
                code = const.FinanceLogCodes.lastschrift_transaction_failure
                lastschrift_update = {
                    'id': lastschrift['id'],
                    'revoked_at': now(),
                }
                self.set_lastschrift(rs, lastschrift_update)
            elif status == const.LastschriftTransactionStati.cancelled:
                code = const.FinanceLogCodes.lastschrift_transaction_cancelled
            else:
                raise RuntimeError(n_("Impossible."))
            self.core.finance_log(rs, code, persona_id, delta, new_balance,
                                  change_note=str(update['tally']))
        return ret

    @access("finance_admin")
    def finalize_lastschrift_transactions(
            self, rs: RequestState, transaction_ids: Collection[int],
            status: const.LastschriftTransactionStati
    ) -> DefaultReturnCode:
        """Atomized multiplex variant of finalize_lastschrift_transaction."""
        transaction_ids = affirm_array(vtypes.ID, transaction_ids)
        status = affirm(const.LastschriftTransactionStati, status)
        code = 1
        with Atomizer(rs):
            for transaction_id in transaction_ids:
                code *= self.finalize_lastschrift_transaction(
                    rs, transaction_id, status)
        return code

    @access("finance_admin")
    def rollback_lastschrift_transaction(
            self, rs: RequestState, transaction_id: int) -> DefaultReturnCode:
        """Revert a successful direct debit transaction.

        This happens if the creditor revokes a successful transaction,
        which is possible for some weeks. We deduct the now non-existing
        money from the balance and invalidate the permit.
        """
        transaction_id = affirm(vtypes.ID, transaction_id)
        with Atomizer(rs):
            transaction = self.get_lastschrift_transaction(rs, transaction_id)
            lastschrift = self.get_lastschrift(rs, transaction['lastschrift_id'])
            if transaction['status'] != const.LastschriftTransactionStati.success:
                raise RuntimeError(n_("Transaction was not successful."))
            update = {
                'id': transaction_id,
                'processed_at': now(),
                'tally': -self.conf["SEPA_ROLLBACK_FEE"],
                'status': const.LastschriftTransactionStati.rollback,
            }
            ret = self.sql_update(rs, "cde.lastschrift_transactions", update)
            persona_id = lastschrift['persona_id']
            current = self.core.get_cde_user(rs, persona_id)
            # TODO notify this happens
            # Ensure the balance does not get negative, f.e. if the MEMBERSHIP_FEE
            #  changed between finalization and rollback or membership fee was deducted
            #  from balance as part of the semester management.
            new_balance = max(
                decimal.Decimal(0), current['balance'] - self.annual_membership_fee(rs))
            self.core.change_persona_balance(
                rs, persona_id, new_balance,
                const.FinanceLogCodes.lastschrift_transaction_revoked,
                change_note="Einzug zurückgebucht.")
            lastschrift_update = {
                'id': lastschrift['id'],
                'revoked_at': now(),
            }
            self.set_lastschrift(rs, lastschrift_update)
        return ret

    def lastschrift_may_skip(self, rs: RequestState, lastschrift: CdEDBObject) -> bool:
        """Check whether a direct debit permit may stay dormant for now.

        The point is, that consecutive skips will invalidat the
        permit, after three years of being unused. Thus only a certain
        number of skips will be allowed.
        """
        if now() - datetime.timedelta(days=2 * 365) < lastschrift['granted_at']:
            # If the permit is new enough we are clear.
            return True
        with Atomizer(rs):
            period = self.current_period(rs)
            cutoff = period - 3 * self.conf["PERIODS_PER_YEAR"] + 1
            relevant_periods = tuple(range(cutoff, period + 1))
            ids = self.list_lastschrift_transactions(
                rs, lastschrift_ids=(lastschrift['id'],),
                stati=(const.LastschriftTransactionStati.success,),
                periods=relevant_periods)
        return bool(ids)

    @access("finance_admin")
    def lastschrift_skip(self, rs: RequestState,
                         lastschrift_id: int) -> DefaultReturnCode:
        """Defer invoking a direct debit permit.

        A member may decide to pause donations. We create a respective
        entry/pseudo transaction, so that this is logged correctly.

        This fails (and returns 0) if the action is deferred for too
        long, since the permit is invalidated if it stays unused for
        three years.
        """
        lastschrift_id = affirm(vtypes.ID, lastschrift_id)
        with Atomizer(rs):
            lastschrift = self.get_lastschrift(rs, lastschrift_id)
            if not self.lastschrift_may_skip(rs, lastschrift):
                # Skipping will invalidate permit.
                return 0
            if lastschrift['revoked_at']:
                raise RuntimeError(n_("Lastschrift already revoked."))
            period = self.current_period(rs)
            insert = {
                'submitted_by': rs.user.persona_id,
                'lastschrift_id': lastschrift_id,
                'period_id': period,
                'amount': decimal.Decimal(0),
                'tally': decimal.Decimal(0),
                'issued_at': now(),
                'processed_at': now(),
                'status': const.LastschriftTransactionStati.skipped,
            }
            ret = self.sql_insert(rs, "cde.lastschrift_transactions", insert)
            self.core.finance_log(
                rs, const.FinanceLogCodes.lastschrift_transaction_skip,
                lastschrift['persona_id'], None, None)
        return ret
