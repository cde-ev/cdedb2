#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

import datetime
import decimal

from cdedb.backend.common import (
    access, affirm_validation as affirm, AbstractBackend,
    affirm_set_validation as affirm_set, singularize, batchify)
from cdedb.common import (
    glue, merge_dicts, PrivilegeError, unwrap, now, LASTSCHRIFT_FIELDS,
    LASTSCHRIFT_TRANSACTION_FIELDS, ORG_PERIOD_FIELDS, EXPULS_PERIOD_FIELDS)
from cdedb.query import QueryOperators
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const

class CdEBackend(AbstractBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"

    def __init__(self, configpath):
        super().__init__(configpath)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def cde_log(self, rs, code, persona_id, additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.CdeLogCodes`.
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        if rs.is_quiet:
            return 0
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,
        }
        return self.sql_insert(rs, "cde.log", data)

    @access("cde_admin")
    def retrieve_cde_log(self, rs, codes=None, persona_id=None, start=None,
                         stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type persona_id: int or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        return self.generic_retrieve_log(
            rs, "enum_cdelogcodes", "persona", "cde.log", codes, persona_id,
            start, stop)

    @access("core_admin", "cde_admin")
    def retrieve_finance_log(self, rs, codes=None, persona_id=None, start=None,
                             stop=None):
        """Get financial activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        codes = affirm_set("enum_financelogcodes", codes, allow_None=True)
        persona_id = affirm("id_or_None", persona_id)
        start = affirm("int_or_None", start)
        stop = affirm("int_or_None", stop)
        start = start or 0
        if stop:
            stop = max(start, stop)
        query = glue(
            "SELECT ctime, code, submitted_by, persona_id, delta, new_balance,",
            "additional_info, members, total FROM cde.finance_log {}",
            "ORDER BY id DESC")
        if stop:
            query = glue(query, "LIMIT {}".format(stop-start))
        if start:
            query = glue(query, "OFFSET {}".format(start))
        condition = ""
        params = []
        if codes:
            condition = glue(condition, "WHERE code = ANY(%s)")
            params.append(codes)
        query = query.format(condition)
        return self.query_all(rs, query, params)

    @access("member")
    def list_lastschrift(self, rs, persona_ids=None, active=True):
        """List all direct debit permits.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_ids: [int] or None
        :param persona_ids: If this is not None show only those
          permits belonging to ids in the list.
        :type active: bool or None
        :param active: If this is not None show only those permits which
          are (not) active.
        :rtype: {int: int}
        :returns: Mapping of lastschrift ids to granting persona.
        """
        persona_ids = affirm_set("id", persona_ids, allow_None=True)
        active = affirm("bool_or_None", active)
        query = "SELECT id, persona_id FROM cde.lastschrift"
        params = []
        connector = "WHERE"
        if persona_ids:
            query = glue(query, "{} persona_id = ANY(%s)".format(connector))
            params.append(persona_ids)
            connector = "AND"
        if active is not None:
            operator = "IS" if active else "IS NOT"
            query = glue(query, "{} revoked_at {} NULL".format(connector,
                                                               operator))
        data = self.query_all(rs, query, params)
        return {e['id']: e['persona_id'] for e in data}

    @access("member")
    @singularize("get_lastschrift")
    def get_lastschrifts(self, rs, ids):
        """Retrieve direct debit permits.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: Mapping ids to data sets.
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "cde.lastschrift", LASTSCHRIFT_FIELDS, ids)
        if (not self.is_admin(rs)
                and any(e['persona_id'] != rs.user.persona_id for e in data)):
            raise PrivilegeError("Not privileged.")
        return {e['id']: e for e in data}

    @access("cde_admin")
    def set_lastschrift(self, rs, data):
        """Modify a direct debit permit.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: standard return code
        """
        data = affirm("lastschrift", data)
        with Atomizer(rs):
            ## First check whether we revoke a lastschrift
            log_code = const.FinanceLogCodes.modify_lastschrift
            if data.get('revoked_at'):
                current = unwrap(self.sql_select_one(
                    rs, "cde.lastschrift", ("revoked_at",), data['id']))
                if not current:
                    log_code = const.FinanceLogCodes.revoke_lastschrift
            ## Now make the change
            ret = self.sql_update(rs, "cde.lastschrift", data)
            persona_id = unwrap(self.sql_select_one(
                rs, "cde.lastschrift", ("persona_id",), data['id']))
            self.core.finance_log(rs, log_code, persona_id, None, None)
        return ret

    @access("cde_admin")
    def create_lastschrift(self, rs, data):
        """Make a new direct debit permit.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new direct debit permit
        """
        data = affirm("lastschrift", data, creation=True)
        data['submitted_by'] = rs.user.persona_id
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "cde.lastschrift", data)
            self.core.finance_log(rs, const.FinanceLogCodes.grant_lastschrift,
                                  data['persona_id'], None, None)
        return new_id

    @access("member")
    def list_lastschrift_transactions(self, rs, lastschrift_ids=None,
                                      stati=None, periods=None):
        """List direct debit transactions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lastschrift_ids: [int] or None
        :param lastschrift_ids: If this is not None show only those
          transactions originating with ids in the list.
        :type stati: [int] or None
        :param stati: If this is not None show only transactions with these
          statuses.
        :type periods: [int] or None
        :param periods: If this is not None show only those transactions in
          the specified periods.
        :rtype: {int: int}
        :returns: Mapping of transaction ids to direct debit permit ids.
        """
        lastschrift_ids = affirm_set("id", lastschrift_ids, allow_None=True)
        stati = affirm_set("enum_lastschrifttransactionstati", stati,
                           allow_None=True)
        periods = affirm_set("id", periods, allow_None=True)
        query = "SELECT id, lastschrift_id FROM cde.lastschrift_transactions"
        params = []
        connector = "WHERE"
        if lastschrift_ids:
            query = glue(query, "{} lastschrift_id = ANY(%s)".format(connector))
            params.append(lastschrift_ids)
            connector = "AND"
        if stati:
            query = glue(query, "{} status = ANY(%s)".format(connector))
            params.append(stati)
            connector = "AND"
        if periods:
            query = glue(query, "{} period_id = ANY(%s)".format(connector))
            params.append(periods)
        data = self.query_all(rs, query, params)
        return {e['id']: e['lastschrift_id'] for e in data}

    @access("member")
    @singularize("get_lastschrift_transaction")
    def get_lastschrift_transactions(self, rs, ids):
        """Retrieve direct debit transactions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: Mapping ids to data sets.
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "cde.lastschrift_transactions",
                               LASTSCHRIFT_TRANSACTION_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("cde_admin")
    @batchify("issue_lastschrift_transaction_batch")
    def issue_lastschrift_transaction(self, rs, data, check_unique=False):
        """Make a new direct debit transaction.

        This only creates the database entry. The SEPA file will be
        generated in the frontend.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type check_unique: bool
        :param check_unique: If True: raise an error if there already is an
          issued transaction.
        :rtype: int
        :returns: The id of the new transaction.
        """
        stati = const.LastschriftTransactionStati
        data = affirm("lastschrift_transaction", data, creation=True)
        with Atomizer(rs):
            lastschrift = unwrap(self.get_lastschrifts(
                rs, (data['lastschrift_id'],)))
            if lastschrift['revoked_at']:
                raise RuntimeError("Lastschrift already revoked.")
            period = self.current_period(rs)
            if check_unique:
                transaction_ids = self.list_lastschrift_transactions(
                    rs, lastschrift_ids=(data['lastschrift_id'],),
                    periods=(period,), stati=(stati.issued,))
                if transaction_ids:
                    raise RuntimeError("Existing pending transaction.")
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
                additional_info=data['amount'])
            return ret

    @access("cde_admin")
    def finalize_lastschrift_transaction(self, rs, transaction_id, status,
                                         tally=None):
        """Tally a direct debit transaction.

        That is either book the successful transaction, book the fees for a
        failure or cancel the transaction alltogether.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type transaction_id: int
        :type status: `cdedb.database.constants.LastschriftTransactionStati`
        :param status: If this is ``failed`` the direct debit permit is revoked
          so that no further transactions are issued for it.
        :type tally: decimal.Decimal or None
        :param tally: The actual amount of money that was moved. This may be
          negative if we incur fees for failed transactions. In case of
          success the balance of the persona is increased by the yearly
          membership fee.
        :rtype: int
        :returns: Standard return code.
        """
        transaction_id = affirm("id", transaction_id)
        status = affirm("enum_lastschrifttransactionstati", status)
        if not status.is_finalized():
            raise RuntimeError("Non-final target state.")
        tally = affirm("decimal_or_None", tally)
        with Atomizer(rs):
            transaction = unwrap(self.get_lastschrift_transactions(
                rs, (transaction_id,)))
            current = const.LastschriftTransactionStati(transaction['status'])
            if current.is_finalized():
                raise RuntimeError("Transaction already tallied.")
            if tally is None:
                if status == const.LastschriftTransactionStati.success:
                    tally = transaction['amount']
                elif status == const.LastschriftTransactionStati.cancelled:
                    tally = decimal.Decimal(0)
                else:
                    raise ValueError("Missing tally for failed transaction.")
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
                current = self.core.get_cde_user(rs, persona_id)
                fee = self.conf.PERIODS_PER_YEAR * self.conf.MEMBERSHIP_FEE
                delta = min(tally, fee)
                new_balance = current['balance'] + delta
                self.core.change_persona_balance(
                    rs, persona_id, new_balance,
                    const.FinanceLogCodes.lastschrift_transaction_success,
                    change_note="Successful direct debit transaction.")
                ## Return early since change_persona_balance does the logging
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
                raise RuntimeError("Impossible.")
            self.core.finance_log(rs, code, persona_id, delta, new_balance,
                                  additional_info=update['tally'])
            return ret

    @access("cde_admin")
    def rollback_lastschrift_transaction(self, rs, transaction_id, tally):
        """Revert a successful direct debit transaction.

        This happens if the creditor revokes a successful transaction,
        which is possible for some weeks. We deduct the now non-existing
        money from the balance and invalidate the permit.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type transaction_id: int
        :param tally: The fee incurred by the revokation.
        :rtype: int
        :returns: Standard return code.
        """
        transaction_id = affirm("id", transaction_id)
        tally = affirm("decimal", tally)
        stati = const.LastschriftTransactionStati
        with Atomizer(rs):
            transaction = unwrap(self.get_lastschrift_transactions(
                rs, (transaction_id,)))
            lastschrift = unwrap(self.get_lastschrifts(
                rs, (transaction['lastschrift_id'],)))
            if transaction['status'] != stati.success:
                raise RuntimeError("Transaction was not successful.")
            update = {
                'id': transaction_id,
                'processed_at': now(),
                'tally': tally,
                'status': stati.rollback,
            }
            ret = self.sql_update(rs, "cde.lastschrift_transactions", update)
            persona_id = lastschrift['persona_id']
            fee = self.conf.PERIODS_PER_YEAR * self.conf.MEMBERSHIP_FEE
            delta = min(transaction['tally'], fee)
            current = self.core.get_cde_user(rs, persona_id)
            new_balance = current['balance'] - delta
            self.core.change_persona_balance(
                rs, persona_id, new_balance,
                const.FinanceLogCodes.lastschrift_transaction_revoked,
                change_note="Revoked direct debit transaction")
            lastschrift_update = {
                'id': lastschrift['id'],
                'revoked_at': now(),
            }
            self.set_lastschrift(rs, lastschrift_update)
            return ret

    def lastschrift_may_skip(self, rs, lastschrift):
        """Check whether a direct debit permit may stay dormant for now.

        The point is, that consecutive skips will invalidat the
        permit, after three years of being unused. Thus only a certain
        number of skips will be allowed.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lastschrift: {str: object}
        :rtype: bool
        """
        if now() - datetime.timedelta(days=2*365) < lastschrift['granted_at']:
            ## If the permit is new enough we are clear.
            return True
        with Atomizer(rs):
            period = self.current_period(rs)
            cutoff = period - 3*self.conf.PERIODS_PER_YEAR + 1
            relevant_periods = tuple(range(cutoff, period + 1))
            ids = self.list_lastschrift_transactions(
                rs, lastschrift_ids=(lastschrift['id'],),
                stati=(const.LastschriftTransactionStati.success,),
                periods=relevant_periods)
            return bool(ids)

    @access("cde_admin")
    def lastschrift_skip(self, rs, lastschrift_id):
        """Defer invoking a direct debit permit.

        A member may decide to pause donations. We create a respective
        entry/pseudo transaction, so that this is logged correctly.

        This fails (and returns 0) if the action is deferred for too
        long, since the permit is invalidated if it stays unused for
        three years.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type lastschrift_id: int
        :rtype: int
        :returns: Standard return code.
        """
        lastschrift_id = affirm("id", lastschrift_id)
        with Atomizer(rs):
            lastschrift = unwrap(self.get_lastschrifts(rs, (lastschrift_id,)))
            if not self.lastschrift_may_skip(rs, lastschrift):
                ## Skipping will invalidate permit.
                return 0
            if lastschrift['revoked_at']:
                raise RuntimeError("Lastschrift already revoked.")
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

    @access("cde_admin")
    def finance_statistics(self, rs):
        """Compute some financial statistics.

        Mostly for use by the 'Semesterverwaltung'.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {str: object}
        """
        ret = {}
        with Atomizer(rs):
            query = glue("SELECT COUNT(*) FROM core.personas",
                         "WHERE is_member = True AND balance < %s",
                         "AND trial_member = False")
            ret['low_balance_members'] = unwrap(self.query_one(
                rs, query, (self.conf.MEMBERSHIP_FEE,)))
            query = glue("SELECT COUNT(*) FROM core.personas",
                         "WHERE is_member = True AND trial_member = True")
            ret['trial_members'] = unwrap(self.query_one(rs, query, tuple()))
            return ret

    @access("cde")
    def current_period(self, rs):
        """Check for the current semester

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: int
        :returns: Id of the current org period.
        """
        query = "SELECT MAX(id) FROM cde.org_period"
        return unwrap(self.query_one(rs, query, tuple()))

    @access("cde")
    def get_period(self, rs, period_id):
        """Get data for a semester

        :type rs: :py:class:`cdedb.common.RequestState`
        :type period_id: int
        :rtype: {str: object}
        """
        period_id = affirm("id", period_id)
        return self.sql_select_one(rs, "cde.org_period", ORG_PERIOD_FIELDS,
                                   period_id)

    @access("cde_admin")
    def set_period(self, rs, period):
        """Set data for the current semester

        :type rs: :py:class:`cdedb.common.RequestState`
        :type period: {str: object}
        :rtype: int
        :returns: standard return code
        """
        period = affirm("period", period)
        with Atomizer(rs):
            current_id = self.current_period(rs)
            if period['id'] != current_id:
                raise RuntimeError("Only able to modify current period.")
            return self.sql_update(rs, "cde.org_period", period)

    @access("cde_admin")
    def create_period(self, rs):
        """Make a new semester.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: int
        :returns: ID of new semester
        """
        with Atomizer(rs):
            current_id = self.current_period(rs)
            current = self.get_period(rs, current_id)
            if not current['balance_done']:
                raise RuntimeError("Current period not finalized.")
            new_period = {
                'id': current_id + 1,
                'billing_state': None,
                'billing_done': None,
                'ejection_state': None,
                'ejection_done': None,
                'balance_state': None,
                'balance_done': None,
            }
            ret = self.sql_insert(rs, "cde.org_period", new_period)
            self.cde_log(rs, const.CdeLogCodes.advance_semester,
                         persona_id=None, additional_info=ret)
            return ret

    @access("cde_admin")
    def current_expuls(self, rs):
        """Check for the current expuls number

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: int
        :returns: Id of the current expuls period.
        """
        query = "SELECT MAX(id) FROM cde.expuls_period"
        return unwrap(self.query_one(rs, query, tuple()))

    @access("cde_admin")
    def get_expuls(self, rs, expuls_id):
        """Get data for the an expuls.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type expuls_id: int
        :rtype: {str: object}
        """
        expuls_id = affirm("id", expuls_id)
        return self.sql_select_one(rs, "cde.expuls_period",
                                   EXPULS_PERIOD_FIELDS, expuls_id)

    @access("cde_admin")
    def set_expuls(self, rs, expuls):
        """Set data for the an expuls

        :type rs: :py:class:`cdedb.common.RequestState`
        :type expuls: {str: object}
        :rtype: int
        :returns: standard return code
        """
        expuls = affirm("expuls", expuls)
        with Atomizer(rs):
            current_id = self.current_expuls(rs)
            if expuls['id'] != current_id:
                raise RuntimeError("Only able to modify current expuls.")
            return self.sql_update(rs, "cde.expuls_period", expuls)

    @access("cde_admin")
    def create_expuls(self, rs):
        """Make a new expuls.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: int
        :returns: ID of new expuls
        """
        with Atomizer(rs):
            current_id = self.current_expuls(rs)
            current = self.get_expuls(rs, current_id)
            if not current['addresscheck_done']:
                raise RuntimeError("Current expuls not finalized.")
            new_expuls = {
                'id': current_id + 1,
                'addresscheck_state': None,
                'addresscheck_done': None,
            }
            ret = self.sql_insert(rs, "cde.expuls_period", new_expuls)
            self.cde_log(rs, const.CdeLogCodes.advance_expuls,
                         persona_id=None, additional_info=ret)
            return ret

    @access("searchable")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("query", query)
        if query.scope == "qview_cde_member":
            query.constraints.append(
                ("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(
                ("is_member", QueryOperators.equal, True))
            query.constraints.append(
                ("is_searchable", QueryOperators.equal, True))
            query.constraints.append(
                ("is_archived", QueryOperators.equal, False))
            query.spec['is_cde_realm'] = "bool"
            query.spec['is_member'] = "bool"
            query.spec['is_searchable'] = "bool"
            query.spec["is_archived"] = "bool"
        elif query.scope == "qview_cde_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(
                ("is_cde_realm", QueryOperators.equal, True))
            query.constraints.append(
                ("is_archived", QueryOperators.equal, False))
            query.spec['is_cde_realm'] = "bool"
            query.spec["is_archived"] = "bool"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query)
