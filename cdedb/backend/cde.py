#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

import copy
import datetime
import decimal
from collections import OrderedDict
from typing import Any, Collection, Dict, List, Optional, Protocol, Tuple

import psycopg2.extensions

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    AbstractBackend, access, affirm_array_validation as affirm_array,
    affirm_set_validation as affirm_set, affirm_validation as affirm,
    affirm_validation_optional as affirm_optional, batchify, singularize,
)
from cdedb.backend.past_event import PastEventBackend
from cdedb.common import (
    EXPULS_PERIOD_FIELDS, LASTSCHRIFT_FIELDS, LASTSCHRIFT_TRANSACTION_FIELDS,
    ORG_PERIOD_FIELDS, PARSE_OUTPUT_DATEFORMAT, ArchiveError, CdEDBLog, CdEDBObject,
    CdEDBObjectMap, DefaultReturnCode, DeletionBlockers, LineResolutions, PathLike,
    PrivilegeError, QuotaException, RequestState, glue, implying_realms, make_proxy,
    merge_dicts, n_, now, unwrap,
)
from cdedb.database.connection import Atomizer
from cdedb.filter import money_filter
from cdedb.query import Query, QueryOperators, QueryScope, QuerySpecEntry
from cdedb.validation import PERSONA_CDE_CREATION as CDE_TRANSITION_FIELDS, is_optional


class CdEBackend(AbstractBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"

    def __init__(self, configpath: PathLike = None):
        super().__init__(configpath)
        self.pastevent = make_proxy(PastEventBackend(configpath), internal=True)

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def cde_log(self, rs: RequestState, code: const.CdeLogCodes,
                persona_id: int = None, change_note: str = None
                ) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "change_note": change_note,
        }
        return self.sql_insert(rs, "cde.log", data)

    @access("cde_admin", "auditor")
    def retrieve_cde_log(self, rs: RequestState,
                         codes: Collection[const.CdeLogCodes] = None,
                         offset: int = None, length: int = None,
                         persona_id: int = None, submitted_by: int = None,
                         change_note: str = None,
                         time_start: datetime.datetime = None,
                         time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        return self.generic_retrieve_log(
            rs, const.CdeLogCodes, "persona", "cde.log", codes=codes,
            offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)

    @access("core_admin", "cde_admin", "auditor")
    def retrieve_finance_log(self, rs: RequestState,
                             codes: Collection[const.FinanceLogCodes] = None,
                             offset: int = None, length: int = None,
                             persona_id: int = None, submitted_by: int = None,
                             change_note: str = None,
                             time_start: datetime.datetime = None,
                             time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get financial activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        additional_columns = ["delta", "new_balance", "members", "total"]
        return self.generic_retrieve_log(
            rs, const.FinanceLogCodes, "persona", "cde.finance_log",
            codes=codes, offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, additional_columns=additional_columns,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    @access("core_admin", "cde_admin")
    def change_membership(
            self, rs: RequestState, persona_id: int, is_member: bool
    ) -> Tuple[DefaultReturnCode, List[int], bool]:
        """Special modification function for membership.

        This is similar to the version from the core backend, but can
        additionally handle lastschrift permits.

        In the general situation this variant should be used.

        :param is_member: Desired target state of membership.
        :returns: A tuple containing the return code, a list of ids of
            revoked lastschrift permits and whether any in-flight
            transactions are affected.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        is_member = affirm(bool, is_member)
        code = 1
        revoked_permits = []
        collateral_transactions = False
        with Atomizer(rs):
            if not is_member:
                lastschrift_ids = self.list_lastschrift(
                    rs, persona_ids=(persona_id,), active=None)
                lastschrifts = self.get_lastschrifts(
                    rs, lastschrift_ids.keys())
                active_permits = []
                for lastschrift in lastschrifts.values():
                    if not lastschrift['revoked_at']:
                        active_permits.append(lastschrift['id'])
                if active_permits:
                    if self.list_lastschrift_transactions(
                            rs, lastschrift_ids=active_permits,
                            stati=(const.LastschriftTransactionStati.issued,)):
                        collateral_transactions = True
                    for active_permit in active_permits:
                        data = {
                            'id': active_permit,
                            'revoked_at': now(),
                        }
                        lastschrift_code = self.set_lastschrift(rs, data)
                        if lastschrift_code <= 0:
                            raise ValueError(n_(
                                "Failed to revoke active lastschrift permit"))
                        revoked_permits.append(active_permit)
            code = self.core.change_membership_easy_mode(rs, persona_id, is_member)
        return code, revoked_permits, collateral_transactions

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
    def create_lastschrift(self, rs: RequestState,
                           data: CdEDBObject) -> DefaultReturnCode:
        """Make a new direct debit permit."""
        data = affirm(vtypes.Lastschrift, data, creation=True)
        data['submitted_by'] = rs.user.persona_id
        with Atomizer(rs):
            if self.list_lastschrift(rs, persona_ids=(data['persona_id'],),
                                     active=True):
                raise ValueError(n_("Multiple active permits are disallowed."))
            new_id = self.sql_insert(rs, "cde.lastschrift", data)
            self.core.finance_log(rs, const.FinanceLogCodes.grant_lastschrift,
                                  data['persona_id'], None, None)
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
    def issue_lastschrift_transaction(self, rs: RequestState, data: CdEDBObject,
                                      check_unique: bool = False
                                      ) -> DefaultReturnCode:
        """Make a new direct debit transaction.

        This only creates the database entry. The SEPA file will be
        generated in the frontend.

        :param check_unique: If True: raise an error if there already is an
          issued transaction.
        :returns: The id of the new transaction.
        """
        stati = const.LastschriftTransactionStati
        data = affirm(vtypes.LastschriftTransaction, data, creation=True)
        with Atomizer(rs):
            lastschrift = unwrap(self.get_lastschrifts(
                rs, (data['lastschrift_id'],)))
            if lastschrift['revoked_at']:
                raise RuntimeError(n_("Lastschrift already revoked."))
            period = self.current_period(rs)
            if check_unique:
                transaction_ids = self.list_lastschrift_transactions(
                    rs, lastschrift_ids=(data['lastschrift_id'],),
                    periods=(period,), stati=(stati.issued,))
                if transaction_ids:
                    raise RuntimeError(n_("Existing pending transaction."))
            update = {
                'submitted_by': rs.user.persona_id,
                'period_id': period,
                'status': stati.issued,
            }
            merge_dicts(data, update)
            if 'amount' not in data:
                data['amount'] = lastschrift['amount']
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
            status: const.LastschriftTransactionStati,
            tally: decimal.Decimal = None) -> DefaultReturnCode:
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
        tally = affirm_optional(decimal.Decimal, tally)
        with Atomizer(rs):
            transaction = unwrap(self.get_lastschrift_transactions(
                rs, (transaction_id,)))
            # noinspection PyArgumentList
            current = const.LastschriftTransactionStati(transaction['status'])
            if current.is_finalized():
                raise RuntimeError(n_("Transaction already tallied."))
            if tally is None:
                if status == const.LastschriftTransactionStati.success:
                    tally = transaction['amount']
                elif status == const.LastschriftTransactionStati.cancelled:
                    tally = decimal.Decimal(0)
                else:
                    raise ValueError(
                        n_("Missing tally for failed transaction."))
            update = {
                'id': transaction_id,
                'processed_at': now(),
                'tally': tally,
                'status': status,
            }
            ret = self.sql_update(rs, "cde.lastschrift_transactions", update)
            lastschrift = unwrap(self.get_lastschrifts(
                rs, (transaction['lastschrift_id'],)))
            persona_id = lastschrift['persona_id']
            delta = None
            new_balance = None
            if status == const.LastschriftTransactionStati.success:
                code = const.FinanceLogCodes.lastschrift_transaction_success
                user = self.core.get_cde_user(rs, persona_id)
                periods_per_year = self.conf["PERIODS_PER_YEAR"]
                fee = periods_per_year * self.conf["MEMBERSHIP_FEE"]
                delta = min(tally, fee)
                new_balance = user['balance'] + delta
                ret *= self.core.change_persona_balance(
                    rs, persona_id, new_balance,
                    const.FinanceLogCodes.lastschrift_transaction_success,
                    change_note="Erfolgreicher Lastschrifteinzug.")
                if new_balance >= self.conf["MEMBERSHIP_FEE"]:
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
            self, rs: RequestState, transactions: List[CdEDBObject]
    ) -> DefaultReturnCode:
        """Atomized multiplex variant of finalize_lastschrift_transaction."""
        transactions = affirm_array(vtypes.LastschriftTransactionEntry, transactions)
        code = 1
        with Atomizer(rs):
            for transaction in transactions:
                code *= self.finalize_lastschrift_transaction(
                    rs, transaction['transaction_id'], transaction['status'],
                    tally=transaction['tally'])
        return code

    @access("finance_admin")
    def rollback_lastschrift_transaction(
            self, rs: RequestState, transaction_id: int,
            tally: decimal.Decimal) -> DefaultReturnCode:
        """Revert a successful direct debit transaction.

        This happens if the creditor revokes a successful transaction,
        which is possible for some weeks. We deduct the now non-existing
        money from the balance and invalidate the permit.

        :param tally: The fee incurred by the revokation.
        """
        transaction_id = affirm(vtypes.ID, transaction_id)
        tally = affirm(decimal.Decimal, tally)
        stati = const.LastschriftTransactionStati
        with Atomizer(rs):
            transaction = unwrap(self.get_lastschrift_transactions(
                rs, (transaction_id,)))
            lastschrift = unwrap(self.get_lastschrifts(
                rs, (transaction['lastschrift_id'],)))
            if transaction['status'] != stati.success:
                raise RuntimeError(n_("Transaction was not successful."))
            update = {
                'id': transaction_id,
                'processed_at': now(),
                'tally': tally,
                'status': stati.rollback,
            }
            ret = self.sql_update(rs, "cde.lastschrift_transactions", update)
            persona_id = lastschrift['persona_id']
            fee = self.conf["PERIODS_PER_YEAR"] * self.conf["MEMBERSHIP_FEE"]
            delta = min(transaction['tally'], fee)
            current = self.core.get_cde_user(rs, persona_id)
            new_balance = current['balance'] - delta
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

    def lastschrift_may_skip(self, rs: RequestState,
                             lastschrift: CdEDBObject) -> bool:
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
            lastschrift = unwrap(self.get_lastschrifts(rs, (lastschrift_id,)))
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

    @access("finance_admin")
    def perform_money_transfers(self, rs: RequestState, data: List[CdEDBObject]
                                ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Resolve all money transfer entries.

        :returns: A bool indicating success and:
            * In case of success:
                * The number of recorded transactions
                * The number of new members.
            * In case of error:
                * The index of the erronous line or None
                    if a DB-serialization error occurred.
                * None
        """
        data = affirm_array(vtypes.MoneyTransferEntry, data)
        index = 0
        note_template = ("Guthabenänderung um {amount} auf {new_balance} "
                         "(Überwiesen am {date})")
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count = 0
                memberships_gained = 0
                persona_ids = tuple(e['persona_id'] for e in data)
                personas = self.core.get_total_personas(rs, persona_ids)
                for index, datum in enumerate(data):
                    assert isinstance(datum['amount'], decimal.Decimal)
                    new_balance = (personas[datum['persona_id']]['balance']
                                   + datum['amount'])
                    note = datum['note']
                    if note:
                        try:
                            date = datetime.datetime.strptime(
                                note, PARSE_OUTPUT_DATEFORMAT)
                        except ValueError:
                            pass
                        else:
                            # This is the default case and makes it pretty
                            note = note_template.format(
                                amount=money_filter(datum['amount']),
                                new_balance=money_filter(new_balance),
                                date=date.strftime(PARSE_OUTPUT_DATEFORMAT))
                    count += self.core.change_persona_balance(
                        rs, datum['persona_id'], new_balance,
                        const.FinanceLogCodes.increase_balance,
                        change_note=note)
                    if new_balance >= self.conf["MEMBERSHIP_FEE"]:
                        code, _, _ = self.change_membership(
                            rs, datum['persona_id'], is_member=True)
                        memberships_gained += bool(code)
                    # Remember the changed balance in case of multiple transfers.
                    personas[datum['persona_id']]['balance'] = new_balance
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None, None
        except Exception:
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during transfer processing",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index, None
        return True, count, memberships_gained

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
    def current_period(self, rs: RequestState) -> int:
        """Check for the current semester."""
        query = "SELECT MAX(id) FROM cde.org_period"
        ret = unwrap(self.query_one(rs, query, tuple()))
        if not ret:
            raise ValueError(n_("No period exists."))
        return ret

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

    @access("member", "cde_admin")
    def get_member_stats(self, rs: RequestState
                         ) -> Tuple[CdEDBObject, CdEDBObject, CdEDBObject]:
        """Retrieve some generic statistics about members."""
        # Simple stats first.
        query = """SELECT
            num_members, num_of_searchable, num_of_trial, num_of_printed_expuls,
            num_ex_members, num_all
        FROM
            (
                SELECT COUNT(*) AS num_members
                FROM core.personas
                WHERE is_member = True
            ) AS member_count,
            (
                SELECT COUNT(*) AS num_of_searchable
                FROM core.personas
                WHERE is_member = True AND is_searchable = True
            ) AS searchable_count,
            (
                SELECT COUNT(*) AS num_of_trial
                FROM core.personas
                WHERE is_member = True AND trial_member = True
            ) AS trial_count,
            (
                SELECT COUNT(*) AS num_of_printed_expuls
                FROM core.personas
                WHERE is_member = True and paper_expuls = True
            ) AS printed_expuls_count,
            (
                SELECT COUNT(*) AS num_ex_members
                FROM core.personas
                WHERE is_cde_realm = True AND is_member = False
            ) AS ex_member_count,
            (
                SELECT COUNT(*) AS num_all
                FROM core.personas
            ) AS all_count
        """
        data = self.query_one(rs, query, ())
        assert data is not None

        simple_stats = OrderedDict((k, data[k]) for k in (
            n_("num_members"), n_("num_of_searchable"), n_("num_of_trial"),
            n_("num_of_printed_expuls"), n_("num_ex_members"), n_("num_all")))

        # TODO: improve this type annotation with a new mypy version.
        def query_stats(select: str, condition: str, order: str, limit: int = 0
                        ) -> OrderedDict:  # type: ignore
            query = (f"SELECT COUNT(*) AS num, {select} AS datum"
                     f" FROM core.personas"
                     f" WHERE is_member = True AND {condition} IS NOT NULL"
                     f" GROUP BY datum HAVING COUNT(*) > {limit} ORDER BY {order}")
            data = self.query_all(rs, query, ())
            return OrderedDict((e['datum'], e['num']) for e in data)

        # Members by locations.
        other_stats: CdEDBObject = {
            n_("members_by_country"): query_stats(
                select="country",
                condition="location",
                order="num DESC, datum ASC"),
            n_("members_by_city"): query_stats(
                select="location",
                condition="location",
                order="num DESC, datum ASC",
                limit=9),
        }

        # Members by date.
        year_stats: CdEDBObject = {
            n_("members_by_birthday"): query_stats(
                select="EXTRACT(year FROM birthday)::integer",
                condition="birthday",
                order="datum ASC"),
        }

        # Members by first event.
        query = """SELECT
            COUNT(*) AS num, EXTRACT(year FROM min_tempus.t)::integer AS datum
        FROM
            (
                SELECT persona.id, MIN(pevents.tempus) as t
                FROM
                    (
                        SELECT id FROM core.personas
                        WHERE is_member = TRUE
                    ) as persona
                    LEFT OUTER JOIN (
                        SELECT DISTINCT persona_id, pevent_id
                        FROM past_event.participants
                    ) AS participants ON persona.id = participants.persona_id
                    LEFT OUTER JOIN (
                        SELECT id, tempus
                        FROM past_event.events
                    ) AS pevents ON participants.pevent_id = pevents.id
                WHERE
                    pevents.id IS NOT NULL
                GROUP BY
                    persona.id
            ) AS min_tempus
        GROUP BY
            datum
        ORDER BY
            -- num DESC,
            datum ASC
        """
        year_stats[n_("members_by_first_event")] = OrderedDict(
            (e['datum'], e['num']) for e in self.query_all(rs, query, ()))

        # Unique event attendees per year:
        query = """SELECT
            COUNT(DISTINCT persona_id) AS num,
            EXTRACT(year FROM events.tempus)::integer AS datum
        FROM
            (
                past_event.institutions
                LEFT OUTER JOIN (
                    SELECT id, institution, tempus FROM past_event.events
                ) AS events ON events.institution = institutions.id
                LEFT OUTER JOIN (
                    SELECT persona_id, pevent_id FROM past_event.participants
                ) AS participants ON participants.pevent_id = events.id
            )
        WHERE
            shortname = 'CdE'
        GROUP BY
            datum
        ORDER BY
            datum ASC
        """
        year_stats[n_("unique_participants_per_year")] = dict(
            (e['datum'], e['num']) for e in self.query_all(rs, query, ()))

        return simple_stats, other_stats, year_stats

    def _perform_one_batch_admission(self, rs: RequestState, datum: CdEDBObject,
                                     trial_membership: bool, consent: bool
                                     ) -> Optional[bool]:
        """Uninlined code from perform_batch_admission().

        :returns: None if nothing happened. True if a new member account was created or
            membership was granted to an existing (non-member) account. False if
            (trial-)membership was renewed for an existing (already member) account.
        """
        # Require an Atomizer.
        self.affirm_atomized_context(rs)

        batch_fields = (
            'family_name', 'given_names', 'display_name', 'title', 'name_supplement',
            'birth_name', 'gender', 'address_supplement', 'address',
            'postal_code', 'location', 'country', 'telephone',
            'mobile', 'birthday')  # email omitted as it is handled separately
        if datum['resolution'] == LineResolutions.skip:
            return None
        elif datum['resolution'] == LineResolutions.create:
            new_persona = copy.deepcopy(datum['persona'])
            new_persona.update({
                'is_member': True,
                'trial_member': trial_membership,
                'paper_expuls': True,
                'is_searchable': consent,
            })
            persona_id = self.core.create_persona(rs, new_persona)
            ret = True
        elif datum['resolution'].is_modification():
            ret = False
            persona_id = datum['doppelganger_id']
            current = self.core.get_persona(rs, persona_id)
            if current['is_archived']:
                if current['is_purged']:
                    raise RuntimeError(n_("Cannot restore purged account."))
                self.core.dearchive_persona(
                    rs, persona_id, datum['persona']['username'])
                current['username'] = datum['persona']['username']
            if datum['update_username']:
                if current['username'] != datum['persona']['username']:
                    self.core.change_username(
                        rs, persona_id, datum['persona']['username'], password=None)
            if not current['is_cde_realm']:
                # Promote to cde realm dependent on current realm
                promotion: CdEDBObject = {
                    field: None for field in CDE_TRANSITION_FIELDS}
                # The ream independent upgrades of the persona. They are applied at last
                # to prevent unintentional overrides
                upgrades = {
                    'is_cde_realm': True,
                    'is_event_realm': True,
                    'is_assembly_realm': True,
                    'is_ml_realm': True,
                    'decided_search': False,
                    'trial_member': False,
                    'paper_expuls': True,
                    'bub_search': False,
                    'id': persona_id,
                }
                # This applies a part of the newly imported data necessary for realm
                # transition. The remaining data will be updated later.
                mandatory_fields = {
                    field for field, validator in CDE_TRANSITION_FIELDS.items()
                    if field not in upgrades and not is_optional(validator)
                }
                assert mandatory_fields <= set(batch_fields)
                # It is pure incident that only event users have additional (optional)
                # data they share with cde users and which must be honoured during realm
                # transition. This may be changed if a new user tier is introduced.
                if not current['is_event_realm']:
                    if not datum['resolution'].do_update():
                        raise RuntimeError(n_("Need extra data."))
                    for field in mandatory_fields:
                        promotion[field] = datum['persona'][field]
                else:
                    current = self.core.get_event_user(rs, persona_id)
                    # take care that we do not override existent data
                    current_fields = {
                        field for field in CDE_TRANSITION_FIELDS
                        if current.get(field) is not None
                    }
                    for field in current_fields:
                        promotion[field] = current[field]
                    for field in mandatory_fields:
                        if promotion[field] is None:
                            promotion[field] = datum['persona'][field]
                # apply the actual changes
                promotion.update(upgrades)
                self.core.change_persona_realms(
                    rs, promotion, change_note="Datenübernahme nach Massenaufnahme")
            if datum['resolution'].do_trial():
                code, _, _ = self.change_membership(
                    rs, datum['doppelganger_id'], is_member=True)
                # This will be true if the user was not a member before.
                ret = bool(code)
                update = {
                    'id': datum['doppelganger_id'],
                    'trial_member': True,
                }
                self.core.change_persona(
                    rs, update, may_wait=False,
                    change_note="Probemitgliedschaft erneuert.")
            if datum['resolution'].do_update():
                update = {'id': datum['doppelganger_id']}
                for field in batch_fields:
                    update[field] = datum['persona'][field]
                self.core.change_persona(
                    rs, update, may_wait=True, force_review=True,
                    change_note="Import aktualisierter Daten.")
        else:
            raise RuntimeError(n_("Impossible."))
        if datum['pevent_id'] and persona_id:
            self.pastevent.add_participant(
                rs, datum['pevent_id'], datum['pcourse_id'], persona_id,
                is_instructor=datum['is_instructor'], is_orga=datum['is_orga'])
        return ret

    @access("cde_admin")
    def perform_batch_admission(self, rs: RequestState, data: List[CdEDBObject],
                                trial_membership: bool, consent: bool
                                ) -> Tuple[bool, Optional[int], Optional[int]]:
        """Atomized call to recruit new members.

        The frontend wants to do this in its entirety or not at all, so this
        needs to be in atomized context.

        :returns: A tuple consisting of a bool and two optional integers.:
            A boolean signalling success.
            If the operation was successful:
                An integer signalling the number of newly created accounts.
                An integer signalling the number of modified/renewed accounts.
            If the operation was not successful:
                If a TransactionRollbackError occrured:
                    Both integer parameters are None.
                Otherwise:
                    The index where the error occured.
                    The second parameter is None.
        """
        data = affirm_array(vtypes.BatchAdmissionEntry, data)
        trial_membership = affirm(bool, trial_membership)
        consent = affirm(bool, consent)
        # noinspection PyBroadException
        try:
            with Atomizer(rs):
                count_new = count_renewed = 0
                for index, datum in enumerate(data, start=1):
                    account_created = self._perform_one_batch_admission(
                        rs, datum, trial_membership, consent)
                    if account_created is None:
                        pass
                    elif account_created:
                        count_new += 1
                    else:
                        count_renewed += 1
        except psycopg2.extensions.TransactionRollbackError:
            # We perform a rather big transaction, so serialization errors
            # could happen.
            return False, None, None
        except Exception:
            # This blanket catching of all exceptions is a last resort. We try
            # to do enough validation, so that this should never happen, but
            # an opaque error (as would happen without this) would be rather
            # frustrating for the users -- hence some extra error handling
            # here.
            self.logger.error(glue(
                ">>>\n>>>\n>>>\n>>> Exception during batch creation",
                "<<<\n<<<\n<<<\n<<<"))
            self.logger.exception("FIRST AS SIMPLE TRACEBACK")
            self.logger.error("SECOND TRY CGITB")
            self.cgitb_log()
            return False, index, None
        return True, count_new, count_renewed

    @access("searchable", "core_admin", "cde_admin")
    def submit_general_query(self, rs: RequestState,
                             query: Query) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        if query.scope == QueryScope.cde_member:
            if self.core.check_quota(rs, num=1):
                raise QuotaException(n_("Too many queries."))
            query.constraints.append(("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(("is_member", QueryOperators.equal, True))
            query.constraints.append(("is_searchable", QueryOperators.equal, True))
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.spec['is_cde_realm'] = QuerySpecEntry("bool", "")
            query.spec['is_member'] = QuerySpecEntry("bool", "")
            query.spec['is_searchable'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
        elif query.scope in {QueryScope.cde_user, QueryScope.archived_past_event_user}:
            if not {'core_admin', 'cde_admin'} & rs.user.roles:
                raise PrivilegeError(n_("Admin only."))
            query.constraints.append(("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(
                ("is_archived", QueryOperators.equal,
                 query.scope == QueryScope.archived_past_event_user))
            query.spec['is_cde_realm'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('cde'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = QuerySpecEntry("bool", "")
        elif query.scope == QueryScope.past_event_user:
            if not self.is_admin(rs):
                raise PrivilegeError(n_("Admin only."))
            query.constraints.append(("is_event_realm", QueryOperators.equal, True))
            query.constraints.append(("is_archived", QueryOperators.equal, False))
            query.spec['is_event_realm'] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)
