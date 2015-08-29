#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize, create_fulltext, batchify)
from cdedb.common import (
    glue, PERSONA_DATA_FIELDS, MEMBER_DATA_FIELDS, QuotaException, merge_dicts,
    PrivilegeError, unwrap, now, LASTSCHRIFT_FIELDS,
    LASTSCHRIFT_TRANSACTION_FIELDS)
from cdedb.query import QueryOperators
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse
import datetime
import decimal

class CdEBackend(AbstractUserBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"
    user_management = {
        "data_table": "cde.member_data",
        "data_fields": MEMBER_DATA_FIELDS,
        "validator": "member_data",
        "user_status": const.PersonaStati.member,
    }

    def __init__(self, configpath):
        super().__init__(configpath)

    def establish(self, sessionkey, method, allow_internal=False):
        return super().establish(sessionkey, method,
                                 allow_internal=allow_internal)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def cde_log(self, rs, code, persona_id, additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.CdeLogCodes`.
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "additional_info": additional_info,
        }
        return self.sql_insert(rs, "cde.log", data)

    def finance_log(self, rs, code, persona_id, delta, new_balance,
                    additional_info=None):
        """Make an entry in the finance log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.CdeLogCodes`.
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type delta: decimal or None
        :param delta: change of balance
        :type new_balance: decimal
        :param new_balance: balance of user after the transaction
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "delta": delta,
            "new_balance": new_balance,
            "additional_info": additional_info
        }
        with Atomizer(rs):
            query = glue("SELECT COUNT(*) AS num FROM core.personas",
                         "WHERE status = ANY(%s)")
            data['members'] = unwrap(
                self.query_one(rs, query, (const.MEMBER_STATI,)))
            query = "SELECT SUM(balance) AS num FROM cde.member_data"
            data['total'] = unwrap(self.query_one(rs, query, tuple()))
            return self.sql_insert(rs, "cde.finance_log", data)

    @access("cde_admin")
    def retrieve_cde_log(self, rs, codes=None, persona_id=None, start=None,
                         stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type codes: [int] or None
        :type persona_id: int or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        return self.generic_retrieve_log(
            rs, "enum_cdelogcodes", "persona", "cde.log", codes, persona_id,
            start, stop)

    @access("cde_admin")
    def retrieve_changelog_meta(self, rs, stati=None, start=None, stop=None):
        """Get changelog activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type stati: [int] or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        stati = affirm_array("enum_memberchangestati", stati, allow_None=True)
        start = affirm("int_or_None", start)
        stop = affirm("int_or_None", stop)
        start = start or 0
        if stop:
            stop = max(start, stop)
        query = glue(
            "SELECT submitted_by, reviewed_by, ctime, generation, change_note,",
            "change_status, persona_id FROM core.changelog {} ORDER BY id DESC")
        if stop:
            query = glue(query, "LIMIT {}".format(stop-start))
        if start:
            query = glue(query, "OFFSET {}".format(start))
        condition = ""
        params = []
        if stati:
            condition = glue(condition, "WHERE change_status = ANY(%s)")
            params.append(stati)
        query = query.format(condition)
        return self.query_all(rs, query, params)

    def set_user_data(self, rs, data, generation, allow_username_change=False,
                      allow_finance_change=False, may_wait=True,
                      change_note=''):
        """This checks for privileged fields, implements the change log and
        updates the fulltext in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.set_user_data`
        does. If a change requires review it has to be committed using
        :py:meth:`resolve_change` by an administrator.

        .. note:: Upon losing membership the balance of the account has
                  to be cleared.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :type generation: int or None
        :param generation: generation on which this request is based, if this
           is not the current generation we abort, may be None to override
           the check
        :type allow_username_change: bool
        :param allow_username_change: Usernames are special because they
          are used for login and password recovery, hence we require an
          explicit statement of intent to change a username. Obviously this
          should only be set if necessary.
        :type allow_finance_change: bool
        :param allow_finance_change: The fields ``balance`` and
          ``trial_member`` are special in that they are logged in the
          finance_log. However this logging should happen in the caller, who
          has to set this flag to signal that he did so.
        :type may_wait: bool
        :param may_wait: Whether this change may wait in the changelog. If
          this is ``False`` and there is a pending change in the changelog,
          the new change is slipped in between.
        :type change_note: str
        :param change_note: Comment to record in the changelog entry.
        :rtype: int
        :returns: number of changed entries, however if changes were only
          written to changelog and are waiting for review, the negative number
          of changes written to changelog is returned
        """
        self.affirm_realm(rs, (data['id'],))

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        privileged_fields = {'balance'}
        if set(data) & privileged_fields and not self.is_admin(rs):
            raise PrivilegeError("Modifying sensitive key forbidden.")
        if 'username' in data  and not allow_username_change:
            raise RuntimeError("Modification of username prevented.")
        finance_fields = {'trial_member', 'balance'}
        if set(data) & finance_fields and not allow_finance_change:
            raise RuntimeError("Modification of finance information prevented.")
        if not may_wait and generation is not None:
            raise ValueError("Non-waiting change without generation override.")

        with Atomizer(rs):
            ## Save current state for logging to the finance_log
            if 'status' in data:
                previous = unwrap(self.retrieve_user_data(rs, (data['id'],)))
            else:
                previous = None

            ret = self.core.changelog_submit_change(
                rs, data, generation, change_note=change_note,
                may_wait=may_wait, allow_username_change=allow_username_change)

            if allow_finance_change and ret < 0:
                raise RuntimeError("Finance change not committed.")

            ## Log changes to membership status to the finance_log
            if previous and data['status'] != previous['status']:
                ex_stati = const.ALL_CDE_STATI - const.MEMBER_STATI
                code = None
                if (data['status'] in ex_stati
                        and previous['status'] in const.MEMBER_STATI):
                    code = const.FinanceLogCodes.lose_membership
                elif (data['status'] in const.MEMBER_STATI
                      and previous['status'] in ex_stati):
                    code = const.FinanceLogCodes.gain_membership
                if code is not None:
                    new_balance = data.get('balance', previous['balance'])
                    delta = new_balance - previous['balance']
                    self.finance_log(rs, code, data['id'], delta, new_balance)
            return ret

    @access("cde_admin")
    def resolve_change(self, rs, persona_id, generation, ack,
                       allow_username_change=False, reviewed=True):
        """Review a currently pending change from the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type generation: int
        :type ack: bool
        :param ack: whether to commit or refuse the change
        :type allow_username_change: bool
        :param allow_username_change: Usernames are special because they
          are used for login and password recovery, hence we require an
          explicit statement of intent to change a username. Obviously this
          should only be set if necessary.
        :type reviewed: bool
        :param reviewed: Signals wether the change was reviewed. This exists,
          so that automatically resolved changes are not marked as reviewed.
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("int", persona_id)
        generation = affirm("int", generation)
        ack = affirm("bool", ack)
        allow_username_change = affirm("bool", allow_username_change)

        return self.core.changelog_resolve_change(
            rs, persona_id, generation, ack,
            allow_username_change=allow_username_change, reviewed=reviewed)

    @access("formermember")
    def change_user(self, rs, data, generation, may_wait=True,
                    change_note=None):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :type may_wait: bool
        :param may_wait: override for system requests (which may not wait)
        :type change_note: str
        :param change_note: Descriptive line for changelog
        :rtype: int
        :returns: default return code
        """
        data = affirm("member_data", data)
        generation = affirm("int_or_None", generation)
        may_wait = affirm("bool", may_wait)
        change_note = affirm("str_or_None", change_note)
        if change_note is None:
            self.logger.info("No change note specified (persona_id={}).".format(
                data['id']))
            change_note = "Unspecified change."

        return self.set_user_data(rs, data, generation, may_wait=may_wait,
                                  change_note=change_note)

    @access("event_user")
    @singularize("get_data_no_quota_one")
    def get_data_no_quota(self, rs, ids):
        """This behaves like
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data`, that is
        it does not check or update the quota.

        This is intended for consumption by the event backend, where
        orgas will need access. This should only be used after serious
        consideration. This is a separate function (and not a mere
        parameter to :py:meth:`get_data`) so that its usage can be
        tracked.

        This escalates privileges so non-member orgas are able to utilize
        the administrative interfaces to an event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        orig_conn = None
        if not rs.user.is_member:
            if rs.conn.is_contaminated:
                raise RuntimeError("Atomized -- impossible to escalate.")
            orig_conn = rs.conn
            rs.conn = self.connpool['cdb_member']
        ret = super().get_data(rs, ids)
        if orig_conn:
            rs.conn = orig_conn
        return ret

    @access("formermember")
    @singularize("get_data_outline_one")
    def get_data_outline(self, rs, ids):
        """This is a restricted version of :py:meth:`get_data`.

        It does not incorporate quotas, but returns only a limited
        number of attributes.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        ret = super().get_data(rs, ids)
        fields = ("id", "username", "display_name", "status", "family_name",
                  "given_names", "title", "name_supplement")
        return {key: {k: v for k, v in value.items() if k in fields}
                for key, value in ret.items()}

    @access("formermember")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        """This checks for quota in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data` does.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        ids = affirm_array("int", ids)

        with Atomizer(rs):
            query = glue("SELECT queries FROM core.quota WHERE persona_id = %s",
                         "AND qdate = %s")
            today = now().date()
            num = self.query_one(rs, query, (rs.user.persona_id, today))
            query = glue("UPDATE core.quota SET queries = %s",
                         "WHERE persona_id = %s AND qdate = %s")
            if num is None:
                query = glue("INSERT INTO core.quota",
                             "(queries, persona_id, qdate) VALUES (%s, %s, %s)")
                num = 0
            else:
                num = unwrap(num)
            new = tuple(i == rs.user.persona_id for i in ids).count(False)
            if (num + new > self.conf.MAX_QUERIES_PER_DAY
                    and not self.is_admin(rs)):
                raise QuotaException("Too many queries.")
            if new:
                self.query_exec(rs, query,
                                (num + new, rs.user.persona_id, today))
        return self.retrieve_user_data(rs, ids)

    @access("cde_admin")
    def create_user(self, rs, data, change_note="Member creation."):
        """Make a new member account.

        This caters to the cde realm specifics, foremost the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        data = affirm("member_data", data, creation=True)
        change_note = affirm("str", change_note)
        ## insert default for optional and non-settable fields for changelog
        update = {
            'balance': decimal.Decimal(0),
            'decided_search': False,
            'bub_search': False,
        }
        merge_dicts(data, update)

        with Atomizer(rs):
            new_id = self.core.create_persona(rs, data)
            udata = {k: v for k, v in data.items() if k in MEMBER_DATA_FIELDS}
            udata['persona_id'] = new_id
            udata['fulltext'] = create_fulltext(data)
            self.sql_insert(rs, "cde.member_data", udata,
                            entity_key="persona_id")
            keys = list(PERSONA_DATA_FIELDS + MEMBER_DATA_FIELDS)
            keys.remove("id")
            cdata = {k: data.get(k) for k in keys}
            cdata.update({
                "submitted_by": rs.user.persona_id,
                "generation": 1,
                "change_status": const.MemberChangeStati.committed,
                "persona_id": new_id,
                "change_note": change_note,
            })
            self.sql_insert(rs, "core.changelog", cdata)
            ## It's unlikely but possible to create an account for a former
            ## member
            if data['status'] in const.MEMBER_STATI:
                self.finance_log(rs, const.FinanceLogCodes.new_member,
                                 new_id, data['balance'], data['balance'])
        return new_id

    def genesis_check(self, rs, case_id, secret):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available for cde realm.")

    def genesis(self, rs, case_id, secret, data):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available for cde realm.")

    @access("formermember")
    @singularize("get_generation")
    def get_generations(self, rs, ids):
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: int}
        :returns: dict mapping ids to generations
        """
        ids = affirm_array("int", ids)
        return self.core.changelog_get_generations(rs, ids)

    @access("cde_admin")
    def get_changes(self, rs, stati):
        """Retrive changes in the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type stati: [int]
        :param stati: limit changes to those with a status in this
        :rtype: {int: {str: object}}
        :returns: dict mapping persona ids to dicts containing information
          about the change and the persona
        """
        affirm_array("int", stati)
        return self.core.changelog_get_changes(rs, stati)

    @access("cde_admin")
    def get_history(self, rs, anid, generations):
        """Retrieve history of a member data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type anid: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int: {str: object}}
        :returns: mapping generation to data set
        """
        anid = affirm("int", anid)
        generations = affirm_array("int", generations, allow_None=True)
        return self.core.changelog_get_history(rs, anid, generations)

    @access("formermember")
    @singularize("get_foto")
    def get_fotos(self, rs, ids):
        """Retrieve the profile picture attribute.

        This is separate since it is not logged in the changelog and
        hence not present in :py:data:`cdedb.common.MEMBER_DATA_FIELDS`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: str}
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "cde.member_data", ("persona_id", "foto"),
                               ids, entity_key="persona_id")
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {e['persona_id']: e['foto'] for e in data}

    @access("formermember")
    def set_foto(self, rs, persona_id, foto):
        """Set the profile picture attribute.

        This is separate since it is not logged in the changelog and
        hence not present in :py:data:`cdedb.common.MEMBER_DATA_FIELDS`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type foto: str or None
        :rtype: bool
        """
        persona_id = affirm("int", persona_id)
        foto = affirm("str_or_None", foto)
        if rs.user.persona_id != persona_id and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        data = {
            'persona_id': persona_id,
            'foto': foto,
        }
        num = self.sql_update(rs, "cde.member_data", data,
                              entity_key="persona_id")
        self.cde_log(rs, const.CdeLogCodes.foto_update, persona_id)
        return bool(num)

    @access("formermember")
    def foto_usage(self, rs, foto):
        """Retrieve usage number for a specific foto.

        So we know when a foto is up for garbage collection.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type foto: str
        :rtype: int
        """
        foto = affirm("str", foto)
        query = "SELECT COUNT(*) AS num FROM cde.member_data WHERE foto = %s"
        return unwrap(self.query_one(rs, query, (foto,)))

    @access("member")
    def list_lastschrift(self, rs, active=True):
        """List all direct debit permits.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type active: bool or None
        :param active: If this is not None show only those permits which
          are (not) active.
        :rtype: {int: int}
        :returns: Mapping of lastschrift ids to granting persona.
        """
        active = affirm("bool_or_None", active)
        query = "SELECT id, persona_id FROM cde.lastschrift"
        if active is not None:
            operator = "IS" if active else "IS NOT"
            query = glue(query, "WHERE revoked_at {} NULL".format(operator))
        data = self.query_all(rs, query, tuple())
        return {e['id']: e['persona_id'] for e in data}

    @access("member")
    @singularize("get_lastschrift_one")
    def get_lastschrift(self, rs, ids):
        """Retrieve direct debit permits.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: Mapping ids to data sets.
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "cde.lastschrift", LASTSCHRIFT_FIELDS, ids)
        if (not self.is_admin(rs)
                and any(e['persona_id'] != rs.user.persona_id for e in data)):
            raise PrivilegeError("Not privileged.")
        return {e['id']: e for e in data}

    @access("cde_admin")
    def set_lastschrift(self, rs, data):
        """Modify a direct debit permit.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: standard return code
        """
        data = affirm("lastschrift_data", data)
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
            self.finance_log(rs, log_code, persona_id, None, None)
        return ret

    @access("cde_admin")
    def create_lastschrift(self, rs, data):
        """Make a new direct debit permit.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new direct debit permit
        """
        data = affirm("lastschrift_data", data, creation=True)
        data['submitted_by'] = rs.user.persona_id
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "cde.lastschrift", data)
            self.finance_log(rs, const.FinanceLogCodes.grant_lastschrift,
                             data['persona_id'], None, None)
        return new_id

    @access("member")
    def list_lastschrift_transactions(self, rs, lastschrift_ids=None,
                                      stati=None, periods=None):
        """List direct debit transactions.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type lastschrift_ids: [int] or None
        :param lastschrift_ids: If this is not None show only those
          transactions originating with ids in the list.
        :type stati: [int] or None
        :param stati: If this is not None show only transactions with these
          statuses.
        :type periods: [int] or None
        :param periods: If this is not None show only those
          transactions in the specified periods.
        :rtype: {int: int}
        :returns: Mapping of transaction ids to direct debit permit ids.
        """
        lastschrift_ids = affirm_array("int", lastschrift_ids, allow_None=True)
        stati = affirm_array("int", stati, allow_None=True)
        periods = affirm_array("int", periods, allow_None=True)
        query = "SELECT id, lastschrift_id FROM cde.lastschrift_transactions"
        params = []
        connector = "WHERE"
        if lastschrift_ids:
            query = glue(query, "{} lastschrift_id = ANY(%s)".format(connector))
            params.append(lastschrift_ids)
            connector = "AND"
        if stati is not None:
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: Mapping ids to data sets.
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "cde.lastschrift_transactions",
                               LASTSCHRIFT_TRANSACTION_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("cde_admin")
    @batchify("issue_lastschrift_transaction_batch")
    def issue_lastschrift_transaction(self, rs, data):
        """Make a new direct debit transaction.

        This only creates the database entry. The SEPA file will be
        generated in the frontend.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: The id of the new transaction.
        """
        data = affirm("lastschrift_transaction", data, creation=True)
        with Atomizer(rs):
            lastschrift = unwrap(self.get_lastschrift(
                rs, (data['lastschrift_id'],)))
            if lastschrift['revoked_at']:
                raise RuntimeError("Lastschrift already revoked.")
            query = "SELECT MAX(id) FROM cde.org_period"
            period = unwrap(self.query_one(rs, query, tuple()))
            update = {
                'submitted_by': rs.user.persona_id,
                'period_id': period,
                'status': const.LastschriftTransactionStati.issued,
            }
            merge_dicts(data, update)
            if 'amount' not in data:
                data['amount'] = lastschrift['amount']
            ret = self.sql_insert(rs, "cde.lastschrift_transactions", data)
            self.finance_log(
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        transaction_id = affirm("int", transaction_id)
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
            lastschrift = unwrap(self.get_lastschrift(
                rs, (transaction['lastschrift_id'],)))
            persona_id = lastschrift['persona_id']
            delta = None
            new_balance = None
            if status == const.LastschriftTransactionStati.success:
                code = const.FinanceLogCodes.lastschrift_transaction_success
                current = unwrap(self.get_data(rs, (persona_id,)))
                fee = self.conf.PERIODS_PER_YEAR * self.conf.MEMBERSHIP_FEE
                delta = min(tally, fee)
                new_balance = current['balance'] + delta
                persona_update = {
                    'id': persona_id,
                    'balance': new_balance,
                }
                self.set_user_data(
                    rs, persona_update, generation=None, may_wait=False,
                    allow_finance_change=True,
                    change_note="Successful direct debit transaction")
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
            self.finance_log(rs, code, persona_id, delta, new_balance,
                             additional_info=update['tally'])
            return ret

    def lastschrift_may_skip(self, rs, lastschrift):
        """Check whether a direct debit permit may stay dormant for now.

        The point is, that consecutive skips will invalidat the
        permit, after three years of being unused. Thus only a certain
        number of skips will be allowed.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type lastschrift: {str: object}
        :rtype: bool
        """
        if now() - datetime.timedelta(days=2*365) < lastschrift['granted_at']:
            ## If the permit is new enough we are clear.
            return True
        with Atomizer(rs):
            query = "SELECT MAX(id) FROM cde.org_period"
            period = unwrap(self.query_one(rs, query, tuple()))
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type lastschrift_id: int
        :rtype: int
        :returns: Standard return code.
        """
        lastschrift_id = affirm("int", lastschrift_id)
        with Atomizer(rs):
            lastschrift = unwrap(self.get_lastschrift(rs, (lastschrift_id,)))
            if not self.lastschrift_may_skip(rs, lastschrift):
                ## Skipping will invalidate permit.
                return 0
            if lastschrift['revoked_at']:
                raise RuntimeError("Lastschrift already revoked.")
            query = "SELECT MAX(id) FROM cde.org_period"
            period = unwrap(self.query_one(rs, query, tuple()))
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
            self.finance_log(
                rs, const.FinanceLogCodes.lastschrift_transaction_skip,
                lastschrift['persona_id'], None, None)
            return ret

    @access("searchmember")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("serialized_query", query)
        if query.scope == "qview_cde_member":
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.SEARCHMEMBER_STATI))
            query.spec['status'] = "int"
        elif query.scope == "qview_cde_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.CDE_STATI))
        elif query.scope == "qview_cde_archived_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(("status", QueryOperators.equal,
                                      const.PersonaStati.archived_member))
            query.spec['status'] = "int"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for CdE services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    cde_backend = CdEBackend(args.configpath)
    conf = Config(args.configpath)
    cde_server = make_RPCDaemon(cde_backend, conf.CDE_SOCKET,
                                access_log=conf.CDE_ACCESS_LOG)
    run_RPCDaemon(cde_server, conf.CDE_STATE_FILE)
