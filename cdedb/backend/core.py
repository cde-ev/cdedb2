#!/usr/bin/env python3

"""The core backend provides services which are common for all
users/personas independent of their realm. Thus we have no user role
since the basic division is between known accounts and anonymous
accesses.
"""
import collections
import copy
import datetime
import decimal
import hmac

from passlib.hash import sha512_crypt

from cdedb.backend.common import AbstractBackend
from cdedb.backend.common import (
    access, internal_access, singularize, diacritic_patterns,
    affirm_validation as affirm, affirm_set_validation as affirm_set)
from cdedb.common import (
    n_, glue, GENESIS_CASE_FIELDS, PrivilegeError, unwrap, extract_roles, User,
    PERSONA_CORE_FIELDS, PERSONA_CDE_FIELDS, PERSONA_EVENT_FIELDS,
    PERSONA_ASSEMBLY_FIELDS, PERSONA_ML_FIELDS, PERSONA_ALL_FIELDS,
    PRIVILEGE_CHANGE_FIELDS, privilege_tier, now, QuotaException,
    PERSONA_STATUS_FIELDS, PsycoJson, merge_dicts, PERSONA_DEFAULTS,
    ArchiveError, extract_realms, implied_realms, encode_parameter,
    decode_parameter)
from cdedb.security import secure_token_hex
from cdedb.config import SecretsConfig
from cdedb.database.connection import Atomizer
import cdedb.validation as validate
import cdedb.database.constants as const
from cdedb.query import QueryOperators
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory


class CoreBackend(AbstractBackend):
    """Access to this is probably necessary from everywhere, so we need
    ``@internal_access`` quite often. """
    realm = "core"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath, is_core=True)
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, DATABASE_ROLES,
            secrets, self.conf.DB_PORT)
        self.generate_reset_cookie = (
            lambda rs, persona_id, timeout: self._generate_reset_cookie(
                rs, persona_id, secrets.RESET_SALT, timeout=timeout))
        self.verify_reset_cookie = (
            lambda rs, persona_id, cookie: self._verify_reset_cookie(
                rs, persona_id, secrets.RESET_SALT, cookie))

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def is_relative_admin(self, rs, persona_id, allow_superadmin=False):
        """Check whether the user is privileged with respect to a persona.

        A mailinglist admin may not edit cde users, but the other way
        round it should work.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type allow_superadmin: bool
        :param allow_superadmin: In some cases we need to allow superadmins
            access where they should not normally have it. This is to allow that
            override.
        :rtype: bool
        """
        if self.is_admin(rs):
            return True
        if allow_superadmin and "admin" in rs.user.roles:
            return True
        roles = extract_roles(unwrap(self.get_personas(rs, (persona_id,))),
                              introspection_only=True)
        return any(admin <= rs.user.roles for admin in privilege_tier(roles))

    @staticmethod
    def verify_password(password, password_hash):
        """Central function, so that the actual implementation may be easily
        changed.

        :type password: str
        :type password_hash: str
        :rtype: bool
        """
        return sha512_crypt.verify(password, password_hash)

    @staticmethod
    def encrypt_password(password):
        """We currently use passlib for password protection.

        :type password: str
        :rtype: str
        """
        return sha512_crypt.hash(password)

    @staticmethod
    def create_fulltext(persona):
        """Helper to mangle all data into a single string.

        :type persona: {str: object}
        :param persona: one persona data set to convert into a string for
          fulltext search
        :rtype: str
        """
        attributes = (
            "id", "title", "username", "display_name", "given_names",
            "family_name", "birth_name", "name_supplement", "birthday",
            "telephone", "mobile", "address_supplement", "address",
            "postal_code", "location", "country", "address_supplement2",
            "address2", "postal_code2", "location2", "country2", "weblink",
            "specialisation", "affiliation", "timeline", "interests",
            "free_form")
        values = (str(persona[a]) for a in attributes if persona[a] is not None)
        return " ".join(values)

    def core_log(self, rs, code, persona_id, additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.CoreLogCodes`.
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
         """
        if rs.is_quiet:
            return 0
        # do not use sql_insert since it throws an error for selecting the id
        query = glue(
            "INSERT INTO core.log",
            "(code, submitted_by, persona_id, additional_info)",
            "VALUES (%s, %s, %s, %s)")
        return self.query_exec(
            rs, query, (code, rs.user.persona_id, persona_id, additional_info))

    @internal_access("cde")
    def finance_log(self, rs, code, persona_id, delta, new_balance,
                    additional_info=None):
        """Make an entry in the finance log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of
          :py:class:`cdedb.database.constants.FinanceLogCodes`.
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
        if rs.is_quiet:
            self.logger.warning("Finance log was suppressed.")
            return 0
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "delta": delta,
            "new_balance": new_balance,
            "additional_info": additional_info
        }
        with Atomizer(rs):
            query = glue("SELECT COUNT(*) AS members, SUM(balance) AS total",
                         "FROM core.personas WHERE is_member = True")
            tmp = self.query_one(rs, query, tuple())
            data.update(tmp)
            return self.sql_insert(rs, "cde.finance_log", data)

    @access("core_admin")
    def retrieve_log(self, rs, codes=None, start=None, stop=None,
                     persona_id=None, submitted_by=None,
                     additional_info=None, time_start=None, time_stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type start: int or None
        :type stop: int or None
        :type persona_id: int or None
        :type submitted_by: int or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :rtype: [{str: object}]
        """
        return self.generic_retrieve_log(
            rs, "enum_corelogcodes", "persona", "core.log", codes, start=start,
            stop=stop, persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info, time_start=time_start,
            time_stop=time_stop)

    @access("core_admin")
    def retrieve_changelog_meta(self, rs, stati=None, start=None, stop=None,
                                persona_id=None, submitted_by=None,
                                additional_info=None, time_start=None,
                                time_stop=None, reviewed_by=None):
        """Get changelog activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type stati: [int] or None
        :type start: int or None
        :type stop: int or None
        :type persona_id: id or None
        :type submitted_by: id or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :type reviewed_by: id or None
        :rtype: [{str: object}]
        """
        stati = affirm_set("enum_memberchangestati", stati, allow_None=True)
        start = affirm("int_or_None", start)
        stop = affirm("int_or_None", stop)
        persona_id = affirm("id_or_None", persona_id)
        submitted_by = affirm("id_or_None", submitted_by)
        additional_info = affirm("regex_or_None", additional_info)
        reviewed_by = affirm("id_or_None", reviewed_by)
        time_start = affirm("datetime_or_None", time_start)
        time_stop = affirm("datetime_or_None", time_stop)

        start = start or 0
        if stop:
            stop = max(start, stop)
        query = glue(
            "SELECT submitted_by, reviewed_by, ctime, generation, change_note,",
            "change_status, persona_id FROM core.changelog {} ORDER BY id DESC")
        if stop:
            query = glue(query, "LIMIT {}".format(stop - start))
        if start:
            query = glue(query, "OFFSET {}".format(start))
        connector = "WHERE"
        condition = ""
        params = []
        if stati:
            condition = glue(
                condition, "{} change_status = ANY(%s)".format(connector))
            connector = "AND"
            params.append(stati)
        if submitted_by:
            condition = glue(
                condition, "{} submitted_by = %s".format(connector))
            connector = "AND"
            params.append(submitted_by)
        if reviewed_by:
            condition = glue(condition, "{} reviewed_by = %s".format(connector))
            connector = "AND"
            params.append(reviewed_by)
        if persona_id:
            condition = glue(condition, "{} persona_id = %s".format(connector))
            connector = "AND"
            params.append(persona_id)
        if additional_info:
            condition = glue(condition,
                             "{} change_note ~* %s".format(connector))
            connector = "AND"
            params.append(diacritic_patterns(additional_info))
        if time_start and time_stop:
            condition = glue(condition,
                             "{} %s <= ctime AND ctime <= %s".format(connector))
            connector = "AND"
            params.extend((time_start, time_stop))
        elif time_start:
            condition = glue(condition, "{} %s <= ctime".format(connector))
            connector = "AND"
            params.append(time_start)
        elif time_stop:
            condition = glue(condition, "{} ctime <= %s".format(connector))
            connector = "AND"
            params.append(time_stop)
        query = query.format(condition)
        return self.query_all(rs, query, params)

    def changelog_submit_change(self, rs, data, generation, may_wait,
                                change_note):
        """Insert an entry in the changelog.

        This is an internal helper, that takes care of all the small
        details with regard to e.g. possibly pending changes. If a
        change requires review it has to be committed using
        :py:meth:`changelog_resolve_change` by an administrator.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type generation: int or None
        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
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
        with Atomizer(rs):
            # check for race
            current_generation = unwrap(self.changelog_get_generations(
                rs, (data['id'],)))
            if generation is not None and current_generation != generation:
                self.logger.info("Generation mismatch {} != {} for {}".format(
                    current_generation, generation, data['id']))
                return 0

            # get current state
            history = self.changelog_get_history(
                rs, data['id'], generations=(current_generation,))
            current_state = history[current_generation]

            # handle pending changes
            diff = None
            if (current_state['change_status']
                    == const.MemberChangeStati.pending):
                committed_state = unwrap(self.get_total_personas(
                    rs, (data['id'],)))
                # stash pending change if we may not wait
                if not may_wait:
                    diff = {key: current_state[key] for key in committed_state
                            if committed_state[key] != current_state[key]}
                    current_state.update(committed_state)
                    query = glue("UPDATE core.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND change_status = %s")
                    self.query_exec(rs, query, (
                        const.MemberChangeStati.displaced, data['id'],
                        const.MemberChangeStati.pending))
            else:
                committed_state = current_state

            # determine if something changed
            newly_changed_fields = {key for key, value in data.items()
                                    if value != current_state[key]}
            if not newly_changed_fields:
                if diff:
                    # reenable old change if we were going to displace it
                    query = glue("UPDATE core.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND generation = %s")
                    self.query_exec(rs, query, (const.MemberChangeStati.pending,
                                                data['id'], current_generation))
                # We successfully made the data set match to the requested
                # values. It's not our fault, that we didn't have to do any
                # work.
                return 1

            # Determine if something requiring a review changed.
            fields_requiring_review = {
                "birthday", "family_name", "given_names", "birth_name",
                "gender", "address_supplement", "address", "postal_code",
                "location", "country",
            }
            all_changed_fields = {key for key, value in data.items()
                                  if value != committed_state[key]}
            requires_review = (
                    (all_changed_fields & fields_requiring_review
                     or (current_state['change_status']
                         == const.MemberChangeStati.pending and not diff))
                    and current_state['is_cde_realm']
                    and not ({"core_admin", "cde_admin"} & rs.user.roles))

            # prepare for inserting a new changelog entry
            query = glue("SELECT MAX(generation) AS gen FROM core.changelog",
                         "WHERE persona_id = %s")
            next_generation = unwrap(self.query_one(
                rs, query, (data['id'],))) + 1
            # the following is a nop, if there is no pending change
            query = glue("UPDATE core.changelog SET change_status = %s",
                         "WHERE persona_id = %s AND change_status = %s")
            self.query_exec(rs, query, (
                const.MemberChangeStati.superseded, data['id'],
                const.MemberChangeStati.pending))

            # insert new changelog entry
            insert = copy.deepcopy(current_state)
            insert.update(data)
            insert.update({
                "submitted_by": rs.user.persona_id,
                "reviewed_by": None,
                "generation": next_generation,
                "change_note": change_note,
                "change_status": const.MemberChangeStati.pending,
                "persona_id": data['id'],
            })
            del insert['id']
            if 'ctime' in insert:
                del insert['ctime']
            self.sql_insert(rs, "core.changelog", insert)

            # resolve change if it doesn't require review
            if not requires_review:
                ret = self.changelog_resolve_change(
                    rs, data['id'], next_generation, ack=True, reviewed=False)
            else:
                ret = -1
            if not may_wait and ret <= 0:
                raise RuntimeError(n_("Non-waiting change not committed."))

            # pop the stashed change
            if diff:
                if set(diff) & newly_changed_fields:
                    raise RuntimeError(n_("Conflicting pending change."))
                insert = copy.deepcopy(current_state)
                insert.update(data)
                insert.update(diff)
                insert.update({
                    "submitted_by": rs.user.persona_id,
                    "generation": next_generation + 1,
                    "change_status": const.MemberChangeStati.pending,
                    "persona_id": data['id'],
                    "change_note": "Verdrängte Änderung.",
                })
                del insert['id']
                self.sql_insert(rs, "core.changelog", insert)
        return ret

    @access("core_admin", "cde_admin")
    def changelog_resolve_change(self, rs, persona_id, generation, ack,
                                 reviewed=True):
        """Review a currently pending change from the changelog.

        In practice most changes should be commited without review, so
        that the reviewers won't get plagued too much.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type generation: int
        :type ack: bool
        :param ack: whether to commit or refuse the change
        :type reviewed: bool
        :param reviewed: Signals wether the change was reviewed. This exists,
          so that automatically resolved changes are not marked as reviewed.
        :rtype: int
        :returns: default return code
        """
        if not ack:
            query = glue(
                "UPDATE core.changelog SET reviewed_by = %s,",
                "change_status = %s",
                "WHERE persona_id = %s AND change_status = %s",
                "AND generation = %s")
            return self.query_exec(rs, query, (
                rs.user.persona_id, const.MemberChangeStati.nacked, persona_id,
                const.MemberChangeStati.pending, generation))
        with Atomizer(rs):
            # look up changelog entry and mark as committed
            history = self.changelog_get_history(rs, persona_id,
                                                 generations=(generation,))
            data = history[generation]
            if data['change_status'] != const.MemberChangeStati.pending:
                return 0
            query = glue(
                "UPDATE core.changelog SET {} change_status = %s",
                "WHERE persona_id = %s AND generation = %s")
            query = query.format("reviewed_by = %s," if reviewed else "")
            params = ((rs.user.persona_id,) if reviewed else tuple()) + (
                const.MemberChangeStati.committed, persona_id, generation)
            self.query_exec(rs, query, params)

            # determine changed fields
            old_state = unwrap(self.get_total_personas(rs, (persona_id,)))
            relevant_keys = tuple(key for key in old_state
                                  if data[key] != old_state[key])
            relevant_keys += ('id',)

            udata = {key: data[key] for key in relevant_keys}
            # commit changes
            ret = 0
            if len(udata) > 1:
                ret = self.commit_persona(
                    rs, udata, change_note="Änderung eingetragen.")
                if not ret:
                    raise RuntimeError(n_("Modification failed."))
        return ret

    @access("persona")
    @singularize("changelog_get_generation")
    def changelog_get_generations(self, rs, ids):
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: int}
        :returns: dict mapping ids to generations
        """
        query = glue("SELECT persona_id, max(generation) AS generation",
                     "FROM core.changelog WHERE persona_id = ANY(%s)",
                     "AND change_status = ANY(%s) GROUP BY persona_id")
        valid_status = (const.MemberChangeStati.pending,
                        const.MemberChangeStati.committed)
        data = self.query_all(rs, query, (ids, valid_status))
        return {e['persona_id']: e['generation'] for e in data}

    @access("core_admin")
    def changelog_get_changes(self, rs, stati):
        """Retrive changes in the changelog.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type stati: [int]
        :param stati: limit changes to those with a status in this
        :rtype: {int: {str: object}}
        :returns: dict mapping persona ids to dicts containing information
          about the change and the persona
        """
        stati = affirm_set("enum_memberchangestati", stati)
        query = glue("SELECT persona_id, given_names, family_name,",
                     "generation, ctime",
                     "FROM core.changelog WHERE change_status = ANY(%s)")
        data = self.query_all(rs, query, (stati,))
        return {e['persona_id']: e for e in data}

    @access("persona")
    def changelog_get_history(self, rs, persona_id, generations):
        """Retrieve history of a data set.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int: {str: object}}
        :returns: mapping generation to data set
        """
        persona_id = affirm("id", persona_id)
        if (persona_id != rs.user.persona_id
                and not self.is_relative_admin(
                rs, persona_id, allow_superadmin=True)):
            raise PrivilegeError(n_("Not privileged."))
        generations = affirm_set("int", generations, allow_None=True)
        fields = list(PERSONA_ALL_FIELDS)
        fields.remove('id')
        fields.append("persona_id AS id")
        fields.extend(("submitted_by", "reviewed_by", "ctime", "generation",
                       "change_status", "change_note"))
        query = "SELECT {} FROM core.changelog WHERE persona_id = %s".format(
            ", ".join(fields))
        params = [persona_id]
        if generations:
            query = glue(query, "AND generation = ANY(%s)")
            params.append(generations)
        data = self.query_all(rs, query, params)
        return {e['generation']: e for e in data}

    @internal_access("persona")
    @singularize("retrieve_persona")
    def retrieve_personas(self, rs, ids, columns=PERSONA_CORE_FIELDS):
        """Helper to access a persona dataset.

        Most of the time a higher level function like
        :py:meth:`get_personas` should be used.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :type columns: [str]
        :param columns: Attributes to retrieve.
        :returns: dict mapping ids to requested data
        """
        if "id" not in columns:
            columns += ("id",)
        data = self.sql_select(rs, "core.personas", columns, ids)
        return {d['id']: d for d in data}

    @access("core_admin")
    def next_persona(self, rs, persona_id, is_member=True):
        """Look up the following persona.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type is_member: bool
        :param is_member: If True, restrict to members.
        :rtype: int or None
        :returns: Next valid id in table core.personas
        """
        query = "SELECT MIN(id) FROM core.personas WHERE id > %s"
        if is_member:
            query = glue(query, "AND is_member = True")
        return unwrap(self.query_one(rs, query, (persona_id,)))

    def commit_persona(self, rs, data, change_note):
        """Actually update a persona data set.

        This is the innermost layer of the changelog functionality and
        actually modifies the core.personas table.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type change_note: str or None
        :rtype int:
        :returns: standard return code
        """
        with Atomizer(rs):
            num = self.sql_update(rs, "core.personas", data)
            if not num:
                raise ValueError(n_("Nonexistant user."))
            current = unwrap(self.retrieve_personas(
                rs, (data['id'],), columns=PERSONA_ALL_FIELDS))
            fulltext = self.create_fulltext(current)
            fulltext_update = {
                'id': data['id'],
                'fulltext': fulltext
            }
            self.sql_update(rs, "core.personas", fulltext_update)
            self.core_log(rs, const.CoreLogCodes.persona_change, data['id'],
                          additional_info=change_note)
        return num

    @internal_access("persona")
    def set_persona(self, rs, data, generation=None, change_note=None,
                    may_wait=True, allow_specials=tuple()):
        """Internal helper for modifying a persona data set.

        Most of the time a higher level function like
        :py:meth:`change_persona` should be used.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type generation: int or None
        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :type may_wait: bool
        :param may_wait: Whether this change may wait in the changelog. If
          this is ``False`` and there is a pending change in the changelog,
          the new change is slipped in between.
        :type allow_specials: [str]
        :param allow_specials: Protect some attributes against accidential
          modification. A magic value has to be passed in this array to
          allow modification. This is done by special methods like
          :py:meth:`change_foto` which take care that the necessary
          prerequisites are met.
        :type change_note: str
        :param change_note: Comment to record in the changelog entry. This
          is ignored if the persona is not in the changelog.
        :rtype: int
        :returns: default return code
        """
        if not change_note:
            self.logger.info(
                "No change note specified (persona_id={}).".format(data['id']))
            change_note = "Allgemeine Änderung"

        current = self.sql_select_one(
            rs, "core.personas", ("is_archived", "decided_search"), data['id'])
        if not may_wait and generation is not None:
            raise ValueError(
                n_("Non-waiting change without generation override."))
        realm_keys = {'is_cde_realm', 'is_event_realm', 'is_ml_realm',
                      'is_assembly_realm'}
        if (set(data) & realm_keys
                and ("core_admin" not in rs.user.roles
                     or "realms" not in allow_specials)):
            if (any(data[key] for key in realm_keys)
                    or "archive" not in allow_specials):
                raise PrivilegeError(n_("Realm modification prevented."))
        admin_keys = {'is_cde_admin', 'is_finance_admin', 'is_event_admin',
                      'is_ml_admin', 'is_assembly_admin', 'is_core_admin',
                      'is_admin'}
        if (set(data) & admin_keys
                and ("admin" not in rs.user.roles
                     or "admins" not in allow_specials)):
            # Allow unsetting adminbits during archival.
            if (any(data[key] for key in admin_keys)
                    or "archive" not in allow_specials):
                raise PrivilegeError(
                    n_("Admin privilege modification prevented."))
        if ("is_member" in data
                and (not ({"cde_admin", "core_admin"} & rs.user.roles)
                     or "membership" not in allow_specials)):
            raise PrivilegeError(n_("Membership modification prevented."))
        if (current['decided_search'] and not data.get("is_searchable", True)
                and (not ({"cde_admin", "core_admin"} & rs.user.roles))):
            raise PrivilegeError(n_("Hiding prevented."))
        if ("is_archived" in data
                and ("core_admin" not in rs.user.roles
                     or "archive" not in allow_specials)):
            raise PrivilegeError(n_("Archive modification prevented."))
        if ("balance" in data
                and ("cde_admin" not in rs.user.roles
                     or "finance" not in allow_specials)):
            if not (data["balance"] is None and "archive" in allow_specials):
                raise PrivilegeError(n_("Modification of balance prevented."))
        if "username" in data and "username" not in allow_specials:
            raise PrivilegeError(n_("Modification of email address prevented."))
        if "foto" in data and "foto" not in allow_specials:
            raise PrivilegeError(n_("Modification of foto prevented."))
        if data.get("is_active") and rs.user.persona_id == data['id']:
            raise PrivilegeError(n_("Own activation prevented."))

        # check for permission to edit
        allow_superadmin = data.keys() <= admin_keys | {"id"}
        if (rs.user.persona_id != data['id']
                and not self.is_relative_admin(rs, data['id'],
                                               allow_superadmin)):
            raise PrivilegeError(n_("Not privileged."))

        # Prevent modification of archived members. This check is
        # sufficient since we can only edit our own data if we are not
        # archived.
        if (current['is_archived'] and data.get('is_archived', True)
                and "purge" not in allow_specials):
            raise RuntimeError(n_("Editing archived member impossible."))

        with Atomizer(rs):
            # reroute through the changelog if necessary
            if not self.conf.CDEDB_OFFLINE_DEPLOYMENT:
                ret = self.changelog_submit_change(
                    rs, data, generation=generation,
                    may_wait=may_wait, change_note=change_note)
                if allow_specials and ret < 0:
                    raise RuntimeError(n_("Special change not committed."))
                return ret

            return self.commit_persona(rs, data, change_note)

    @access("persona")
    def change_persona(self, rs, data, generation=None, may_wait=True,
                       change_note=None):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type generation: int or None
        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :type may_wait: bool
        :param may_wait: override for system requests (which may not wait)
        :type change_note: str
        :param change_note: Descriptive line for changelog
        :rtype: int
        :returns: default return code
        """
        data = affirm("persona", data)
        generation = affirm("int_or_None", generation)
        may_wait = affirm("bool", may_wait)
        change_note = affirm("str_or_None", change_note)
        return self.set_persona(rs, data, generation=generation,
                                may_wait=may_wait, change_note=change_note)

    @access("core_admin")
    def change_persona_realms(self, rs, data):
        """Special modification function for realm transitions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("persona", data, transition=True)
        with Atomizer(rs):
            if data.get('is_cde_realm'):
                # Fix balance
                tmp = unwrap(self.get_total_personas(rs, (data['id'],)))
                if tmp['balance'] is None:
                    data['balance'] = decimal.Decimal('0.0')
                else:
                    data['balance'] = tmp['balance']
            return self.set_persona(
                rs, data, may_wait=False,
                change_note="Bereiche geändert.",
                allow_specials=("realms", "finance"))

    @access("persona")
    def change_foto(self, rs, persona_id, foto):
        """Special modification function for foto changes.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type foto: str or None
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("id", persona_id)
        foto = affirm("str_or_None", foto)
        data = {
            'id': persona_id,
            'foto': foto}
        return self.set_persona(
            rs, data, may_wait=False, change_note="Profilbild geändert.",
            allow_specials=("foto",))

    @access("admin")
    def initialize_privilege_change(self, rs, data):
        """Initialize a change to a users admin bits.

        This has to be approved by another admin.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data['submitted_by'] = rs.user.persona_id
        data['status'] = const.PrivilegeChangeStati.pending
        data = affirm("privilege_change", data)

        if "new_is_admin" in data and data['persona_id'] == rs.user.persona_id:
            raise PrivilegeError(n_("Cannot modify own superadmin privileges."))
        if self.get_pending_privilege_change(rs, data['persona_id']):
            raise ValueError(n_("Pending privilege change."))

        persona = unwrap(self.get_total_personas(rs, (data['persona_id'],)))

        realms = {"cde", "event", "ml", "assembly"}
        for realm in realms:
            if not persona['is_{}_realm'.format(realm)]:
                if data.get('new_is_{}_admin'.format(realm)):
                    raise PrivilegeError(n_(
                        "User does not fit the requirements for this "
                        "admin privilege."))

        if data.get('new_is_finance_admin'):
            if (data.get('new_is_cde_admin') is False
                or (not persona['is_cde_admin']
                    and not data.get('new_is_cde_admin'))):
                raise PrivilegeError(n_(
                    "User does not fit the requirements for this "
                    "admin privilege."))

        if data.get('new_is_core_admin') or data.get('new_is_admin'):
            if not persona['is_cde_realm']:
                raise PrivilegeError(n_(
                    "User does not fit the requirements for this "
                    "admin privilege."))

        self.core_log(
            rs, const.CoreLogCodes.privilege_change_pending, data['persona_id'],
            additional_info="Änderung der Admin-Privilegien angestoßen.")

        return self.sql_insert(rs, "core.privilege_changes", data)

    @access("admin")
    def finalize_privilege_change(self, rs, case_id, case_status):
        """Finalize a pending change to a users admin bits.

        This has to be done by a different admin.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :type case_status: int
        :rtype: int
        :returns: default return code
        """
        case_id = affirm("id", case_id)
        case_status = affirm("enum_privilegechangestati", case_status)

        case = self.get_privilege_change(rs, case_id)
        if case['status'] != const.PrivilegeChangeStati.pending:
            raise ValueError(n_("Invalid privilege change state: %(status)s."),
                             {"status": case["status"]})

        data = {
            "id": case_id,
            "ftime": now(),
            "reviewer": rs.user.persona_id,
            "status": case_status,
        }
        with Atomizer(rs):
            if case_status == const.PrivilegeChangeStati.approved:
                if (case["new_is_admin"] is not None
                    and case['persona_id'] == rs.user.persona_id):
                    raise PrivilegeError(
                        n_("Cannot modify own superadmin privileges."))
                if case['submitted_by'] == rs.user.persona_id:
                    raise PrivilegeError(
                        n_("Only a different admin than the submitter "
                           "may approve a privilege change."))

                ret = self.sql_update(rs, "core.privilege_changes", data)

                self.core_log(
                    rs, const.CoreLogCodes.privilege_change_approved,
                    persona_id=case['persona_id'],
                    additional_info="Änderung der Admin-Privilegien bestätigt.")
                data = {
                    "id": case["persona_id"]
                }
                if case["new_is_admin"] is not None:
                    data["is_admin"] = case["new_is_admin"]
                if case["new_is_core_admin"] is not None:
                    data["is_core_admin"] = case["new_is_core_admin"]
                if case["new_is_cde_admin"] is not None:
                    data["is_cde_admin"] = case["new_is_cde_admin"]
                if case["new_is_finance_admin"] is not None:
                    data["is_finance_admin"] = case["new_is_finance_admin"]
                if case["new_is_event_admin"] is not None:
                    data["is_event_admin"] = case["new_is_event_admin"]
                if case["new_is_ml_admin"] is not None:
                    data["is_ml_admin"] = case["new_is_ml_admin"]
                if case["new_is_assembly_admin"] is not None:
                    data["is_assembly_admin"] = case["new_is_assembly_admin"]

                data = affirm("persona", data)
                ret *= self.set_persona(
                    rs, data, may_wait=False,
                    change_note="Admin-Privilegien geändert.",
                    allow_specials=("admins",))

                # Mark case as successful
                data = {
                    "id": case_id,
                    "status": const.PrivilegeChangeStati.successful,
                }
                ret *= self.sql_update(rs, "core.privilege_changes", data)

            elif case_status == const.PrivilegeChangeStati.rejected:
                ret = self.sql_update(rs, "core.privilege_changes", data)

                self.core_log(
                    rs, const.CoreLogCodes.privilege_change_rejected,
                    persona_id=case['persona_id'],
                    additional_info="Änderung der Admin-Privilegien verworfen.")
            else:
                raise ValueError(n_("Invalid new privilege change status."))

        return ret

    @access("admin")
    def list_privilege_changes(self, rs, stati=None):
        """List privilge changes.

        Can be restricted to certain stati.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type stati: [int] or None
        :rtype: {int: {str: object}}
        :returns: dict mapping case ids to dicts containing information about
            the change
        """
        stati = stati or set()
        stati = affirm_set("enum_privilegechangestati", stati)

        query = glue("SELECT id, persona_id, status",
                     "FROM core.privilege_changes")

        constraints = []
        params = []
        if stati:
            constraints.append("status = ANY(%s)")
            params.append(stati)

        if constraints:
            query = glue(query,
                         "WHERE",
                         " AND ".join(constraints))

        data = self.query_all(rs, query, params)
        return {e["id"]: e for e in data}

    @access("admin")
    @singularize("get_privilege_change")
    def get_privilege_changes(self, rs, ids):
        """Retrieve datasets for priviledge changes.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to the requested data.
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(
            rs, "core.privilege_changes", PRIVILEGE_CHANGE_FIELDS, ids)
        return {e["id"]: e for e in data}

    @access("admin")
    def get_pending_privilege_change(self, rs, persona_id):
        """Get a pending privilege change for a persona if any.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :rtype: int or None
        :returns: ID of pending privilege change or None if none exists.
        """
        persona_id = affirm("id", persona_id)

        query = ("SELECT id FROM core.privilege_changes "
                 "WHERE persona_id = %s AND status = %s")
        params = (persona_id, const.PrivilegeChangeStati.pending)

        data = self.query_one(rs, query, params)
        if data:
            ret = data["id"]
        else:
            ret = None
        return ret

    @access("persona")
    def list_admins(self, rs, realm):
        """List all personas with admin privilidges in a given realm.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type realm: str
        :rtype: [int]
        """
        realm = affirm("str", realm)

        query = "SELECT id from core.personas WHERE {constraint}"

        constraint = None
        if realm == "admin":
            constraint = "is_admin = TRUE"
        elif realm == "core":
            constraint = "is_core_admin = TRUE"
        elif realm == "cde":
            constraint = "is_cde_admin = TRUE"
        elif realm == "event":
            constraint = "is_event_admin = TRUE"
        elif realm == "ml":
            constraint = "is_ml_admin = TRUE"
        elif realm == "assembly":
            constraint = "is_assembly_admin = TRUE"

        if constraint is None:
            raise ValueError(n_("No realm provided."))

        query = query.format(constraint=constraint)
        result = self.query_all(rs, query, tuple())

        return [e["id"] for e in result]

    @access("core_admin", "cde_admin")
    def change_persona_balance(self, rs, persona_id, balance, log_code,
                               change_note=None):
        """Special modification function for monetary aspects.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type balance: decimal
        :type log_code: :py:class:`cdedb.database.constants.FinanceLogCodes`.
        :type change_note: str or None
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("id", persona_id)
        balance = affirm("non_negative_decimal", balance)
        log_code = affirm("enum_financelogcodes", log_code)
        change_note = affirm("str_or_None", change_note)
        update = {
            'id': persona_id,
            'balance': balance,
        }
        with Atomizer(rs):
            current = unwrap(self.retrieve_personas(
                rs, (persona_id,), ("balance", "is_cde_realm")))
            if not current['is_cde_realm']:
                raise RuntimeError(
                    n_("Tried to credit balance to non-cde person."))
            if current['balance'] != balance:
                ret = self.set_persona(
                    rs, update, may_wait=False, change_note=change_note,
                    allow_specials=("finance",))
                self.finance_log(rs, log_code, persona_id,
                                 balance - current['balance'], balance)
                return ret
            else:
                return 0

    @access("core_admin", "cde_admin")
    def change_membership(self, rs, persona_id, is_member):
        """Special modification function for membership.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type is_member: bool
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("id", persona_id)
        is_member = affirm("bool", is_member)
        update = {
            'id': persona_id,
            'is_member': is_member,
        }
        with Atomizer(rs):
            current = unwrap(self.retrieve_personas(
                rs, (persona_id,), ('is_member', 'balance', 'is_cde_realm')))
            if not current['is_cde_realm']:
                raise RuntimeError(n_("Not a CdE account."))
            if current['is_member'] == is_member:
                return 0
            if not is_member:
                delta = -current['balance']
                new_balance = decimal.Decimal(0)
                code = const.FinanceLogCodes.lose_membership
                # Do not modify searchability.
                update['balance'] = decimal.Decimal(0)
            else:
                delta = None
                new_balance = None
                code = const.FinanceLogCodes.gain_membership
            ret = self.set_persona(
                rs, update, may_wait=False,
                change_note="Mitgliedschaftsstatus geändert.",
                allow_specials=("membership", "finance"))
            self.finance_log(rs, code, persona_id, delta, new_balance)
            return ret

    @access("core_admin", "cde_admin")
    def archive_persona(self, rs, persona_id, note):
        """Move a persona to the attic.

        This clears most of the data we have about the persona. The
        basic use case is for retiring members of a time long gone,
        which have not been seen for an extended period.

        We keep the following data to enable us to recognize them
        later on to allow readmission:
        * name,
        * date of birth,
        * past events.

        Additionally not all data is purged, since we have separate
        life cycles for different realms. This affects the following.
        * finances: we preserve a log of all transactions for bookkeeping,
        * lastschrift: similarily to finances
        * events: to ensure consistency, events are only deleted en bloc
        * assemblies: these we keep to make the decisions traceable

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type note: str
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("id", persona_id)
        note = affirm("str", note)
        with Atomizer(rs):
            persona = unwrap(self.get_total_personas(rs, (persona_id,)))
            #
            # 1. Do some sanity checks.
            #
            if persona['is_archived']:
                return 0

            # Disallow archival of superadmins to ensure there always remain
            # atleast two.
            if persona['is_admin']:
                raise ArchiveError(n_("Cannot archive superadmins."))

            #
            # 2. Remove complicated attributes (membership, foto and password)
            #
            if persona['is_member']:
                code = self.change_membership(rs, persona_id, is_member=False)
                if not code:
                    raise ArchiveError(n_("Failed to revoke membership."))
            if persona['foto']:
                code = self.change_foto(rs, persona_id, foto=None)
                if not code:
                    raise ArchiveError(n_("Failed to remove foto."))
            # modified version of hash for 'secret' and thus
            # safe/unknown plaintext
            password_hash = (
                "$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
                "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHE/si/")
            query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
            self.query_exec(rs, query, (password_hash, persona_id))
            #
            # 3. Strip all unnecessary attributes
            #
            update = {
                'id': persona_id,
                # 'password_hash' already adjusted
                'username': None,
                'is_active': False,
                'notes': note,  # Note on why the persona was archived.
                'is_admin': False,
                'is_core_admin': False,
                'is_cde_admin': False,
                'is_finance_admin': False,
                'is_event_admin': False,
                'is_ml_admin': False,
                'is_assembly_admin': False,
                'is_cde_realm': False,
                'is_event_realm': False,
                'is_ml_realm': False,
                'is_assembly_realm': False,
                # 'is_member' already adjusted
                'is_searchable': False,
                # 'is_archived' will be done later
                # 'display_name' kept for later recognition
                # 'given_names' kept for later recognition
                # 'family_name' kept for later recognition
                'title': None,
                'name_supplement': None,
                'gender': None,
                # 'birthday' kept for later recognition
                'telephone': None,
                'mobile': None,
                'address_supplement': None,
                'address': None,
                'postal_code': None,
                'location': None,
                'country': None,
                # 'birth_name' kept for later recognition
                'address_supplement2': None,
                'address2': None,
                'postal_code2': None,
                'location2': None,
                'country2': None,
                'weblink': None,
                'specialisation': None,
                'affiliation': None,
                'timeline': None,
                'interests': None,
                'free_form': None,
                'balance': None,
                'decided_search': False,
                'trial_member': False,
                'bub_search': False,
                # 'foto' already adjusted
                # 'fulltext' is set automatically
            }
            self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Archivierung vorbereitet.",
                allow_specials=("archive", "username"))
            #
            # 4. Delete all sessions and quotas
            #
            self.sql_delete(rs, "core.sessions", (persona_id,), "persona_id")
            self.sql_delete(rs, "core.quota", (persona_id,), "persona_id")
            #
            # 5. Handle lastschrift
            #
            lastschrift = self.sql_select(
                rs, "cde.lastschrift", ("id", "revoked_at"), (persona_id,),
                "persona_id")
            if any(not l['revoked_at'] for l in lastschrift):
                raise ArchiveError(n_("Active lastschrift exists."))
            query = glue(
                "UPDATE cde.lastschrift",
                "SET (amount, iban, account_owner, account_address)",
                "= (%s, %s, %s, %s)",
                "WHERE persona_id = %s")
            if lastschrift:
                self.query_exec(rs, query, (0, 0, "", "", persona_id))
            #
            # 6. Handle event realm
            #
            query = glue(
                "SELECT reg.persona_id, MAX(part_end) AS m",
                "FROM event.registrations as reg ",
                "JOIN event.events as event ON reg.event_id = event.id",
                "JOIN event.event_parts as parts ON parts.event_id = event.id",
                "WHERE reg.persona_id = %s"
                "GROUP BY persona_id")
            max_end = self.query_one(rs, query, (persona_id,))
            if max_end and max_end['m'] and max_end['m'] >= now().date():
                raise ArchiveError(n_("Involved in unfinished event."))
            self.sql_delete(rs, "event.orgas", (persona_id,), "persona_id")
            #
            # 7. Handle assembly realm
            #
            query = glue(
                "SELECT ass.id FROM assembly.assemblies as ass",
                "JOIN assembly.attendees as att ON att.assembly_id = ass.id",
                "WHERE att.persona_id = %s AND ass.is_active = True")
            ass_active = self.query_all(rs, query, (persona_id,))
            if ass_active:
                raise ArchiveError(n_("Involved in unfinished assembly."))
            query = glue(
                "UPDATE assembly.attendees SET secret = NULL",
                "WHERE persona_id = %s")
            self.query_exec(rs, query, (persona_id,))
            #
            # 8. Handle ml realm
            #
            self.sql_delete(rs, "ml.subscription_states", (persona_id,),
                            "persona_id")
            self.sql_delete(rs, "ml.subscription_requests", (persona_id,),
                            "persona_id")
            self.sql_delete(rs, "ml.moderators", (persona_id,), "persona_id")
            #
            # 9. Clear logs
            #
            self.sql_delete(rs, "core.log", (persona_id,), "persona_id")
            # finance log stays untouched to keep balance correct
            self.sql_delete(rs, "cde.log", (persona_id,), "persona_id")
            # past event log stays untouched since we keep past events
            # event log stays untouched since events have a separate life cycle
            # assembly log stays since assemblies have a separate life cycle
            self.sql_delete(rs, "ml.log", (persona_id,), "persona_id")
            #
            # 10. Mark archived
            #
            update = {
                'id': persona_id,
                'is_archived': True,
            }
            self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer archiviert.",
                allow_specials=("archive",))
            #
            # 11. Clear changelog
            #
            query = glue(
                "SELECT id FROM core.changelog WHERE persona_id = %s",
                "ORDER BY generation DESC LIMIT 1")
            newest = self.query_one(rs, query, (persona_id,))
            query = glue(
                "DELETE FROM core.changelog",
                "WHERE persona_id = %s AND NOT id = %s")
            ret = self.query_exec(rs, query, (persona_id, newest['id']))
            #
            # 12. Finish
            #
            return ret

    @access("core_admin")
    def dearchive_persona(self, rs, persona_id):
        """Return a persona from the attic to activity.

        This does nothing but flip the archiving bit.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm("id", persona_id)
        with Atomizer(rs):
            update = {
                'id': persona_id,
                'is_archived': False,
            }
            return self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer aus dem Archiv wiederhergestellt.",
                allow_specials=("archive",))

    @access("core_admin", "cde_admin")
    def purge_persona(self, rs, persona_id):
        """Delete all infos about this persona.

        It has to be archived beforehand. Thus we do not have to
        remove a lot since archiving takes care of most of the stuff.

        However we do not entirely delete the entry since this would
        cause havock in other areas (like assemblies), we only
        anonymize the entry by removing all identifying information.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :rtype: int
        :returns: default return code

        """
        persona_id = affirm("id", persona_id)
        with Atomizer(rs):
            persona = unwrap(self.get_total_personas(rs, (persona_id,)))
            if not persona['is_archived']:
                raise RuntimeError(n_("Persona is not archived."))
            #
            # 1. Zap information
            #
            update = {
                'id': persona_id,
                'display_name': "N.",
                'given_names': "N.",
                'family_name': "N.",
                'birthday': None,
                'birth_name': None,
            }
            ret = self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer gelöscht.",
                allow_specials=("admins", "username", "purge"))
            #
            # 2. Clear changelog
            #
            query = glue(
                "SELECT id FROM core.changelog WHERE persona_id = %s",
                "ORDER BY generation DESC LIMIT 1")
            newest = self.query_one(rs, query, (persona_id,))
            query = glue(
                "DELETE FROM core.changelog",
                "WHERE persona_id = %s AND NOT id = %s")
            ret *= self.query_exec(rs, query, (persona_id, newest['id']))
            #
            # 3. Finish
            #
            return ret

    @access("persona")
    def change_username(self, rs, persona_id, new_username, password):
        """Since usernames are used for login, this needs a bit of care.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type new_username: str
        :type password: str or None
        :rtype: (bool, str)
        """
        persona_id = affirm("id", persona_id)
        new_username = affirm("email_or_None", new_username)
        password = affirm("str_or_None", password)
        if new_username is None and not self.is_relative_admin(rs, persona_id):
            return False, n_("Only admins may unset an email address.")
        with Atomizer(rs):
            if new_username and self.verify_existence(rs, new_username):
                # abort if there is already an account with this address
                return False, n_("Name collision.")
            authorized = False
            if self.is_relative_admin(rs, persona_id):
                authorized = True
            elif password:
                data = self.sql_select_one(rs, "core.personas",
                                           ("password_hash",), persona_id)
                if data and self.verify_password(password, unwrap(data)):
                    authorized = True
            if authorized:
                new = {
                    'id': persona_id,
                    'username': new_username,
                }
                change_note = "E-Mail-Adresse geändert."
                if self.set_persona(
                        rs, new, change_note=change_note, may_wait=False,
                        allow_specials=("username",)):
                    return True, new_username
        return False, n_("Failed.")

    @access("persona")
    def foto_usage(self, rs, foto):
        """Retrieve usage number for a specific foto.

        So we know when a foto is up for garbage collection.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type foto: str
        :rtype: int
        """
        foto = affirm("str", foto)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE foto = %s"
        return unwrap(self.query_one(rs, query, (foto,)))

    @access("persona")
    @singularize("get_persona")
    def get_personas(self, rs, ids):
        """Acquire data sets for specified ids.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        return self.retrieve_personas(rs, ids, columns=PERSONA_CORE_FIELDS)

    @access("event")
    @singularize("get_event_user")
    def get_event_users(self, rs, ids):
        """Get an event view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_EVENT_FIELDS)
        if (ids != {rs.user.persona_id}
                and "event_admin" not in rs.user.roles
                and (any(e['is_cde_realm'] for e in ret.values()))):
            # The event user view on a cde user contains lots of personal
            # data. So we require the requesting user to be orga if (s)he
            # wants to view it.
            #
            # This is a bit of a transgression since we access the event
            # schema from the core backend, but we go for security instead of
            # correctness here.
            query = "SELECT event_id FROM event.orgas WHERE persona_id = %s"
            if not self.query_all(rs, query, (rs.user.persona_id,)):
                raise PrivilegeError(n_("Access to CdE data sets inhibited."))
        if any(not e['is_event_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an event user."))
        return ret

    @access("cde")
    @singularize("get_cde_user")
    def get_cde_users(self, rs, ids):
        """Get an cde view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
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
            if (num + new > self.conf.QUOTA_VIEWS_PER_DAY
                    and not {"cde_admin", "core_admin"} & rs.user.roles):
                raise QuotaException(n_("Too many queries."))
            if new:
                self.query_exec(rs, query,
                                (num + new, rs.user.persona_id, today))
            ret = self.retrieve_personas(rs, ids, columns=PERSONA_CDE_FIELDS)
            if any(not e['is_cde_realm'] for e in ret.values()):
                raise RuntimeError(n_("Not a CdE user."))
            if (not {"cde_admin", "core_admin"} & rs.user.roles
                    and ("searchable" not in rs.user.roles
                         and any((e['id'] != rs.user.persona_id
                                  and not e['is_searchable'])
                                 for e in ret.values()))):
                raise RuntimeError(n_("Improper access to member data."))
            return ret

    @access("ml")
    @singularize("get_ml_user")
    def get_ml_users(self, rs, ids):
        """Get an ml view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_ML_FIELDS)
        if any(not e['is_ml_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an ml user."))
        return ret

    @access("assembly")
    @singularize("get_assembly_user")
    def get_assembly_users(self, rs, ids):
        """Get an assembly view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_ASSEMBLY_FIELDS)
        if any(not e['is_assembly_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an assembly user."))
        return ret

    @access("persona")
    @singularize("get_total_persona")
    def get_total_personas(self, rs, ids):
        """Acquire data sets for specified ids.

        This includes all attributes regardless of which realm they
        pertain to.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        if (ids != {rs.user.persona_id} and not self.is_admin(rs)
                and any(not self.is_relative_admin(rs, anid,
                                                   allow_superadmin=True)
                        for anid in ids)):
            raise PrivilegeError(n_("Must be privileged."))
        return self.retrieve_personas(rs, ids, columns=PERSONA_ALL_FIELDS)

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def create_persona(self, rs, data, submitted_by=None):
        """Instantiate a new data set.

        This does the house-keeping and inserts the corresponding entry in
        the changelog.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type submitted_by: int or None
        :param submitted_by: Allow to override the submitter for genesis.
        :rtype: int
        :returns: The id of the newly created persona.
        """
        data = affirm("persona", data, creation=True)
        # zap any admin attempts
        data.update({
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        # Check if admin has rights to create the user in its realms
        if not any(admin <= rs.user.roles
                   for admin in privilege_tier(extract_roles(data),
                                               conjunctive=True)):
            raise PrivilegeError(n_("Unable to create this sort of persona."))
        # modified version of hash for 'secret' and thus safe/unknown plaintext
        data['password_hash'] = (
            "$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
            "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHE/si/")
        # add balance for cde users
        if data.get('is_cde_realm') and 'balance' not in data:
            data['balance'] = decimal.Decimal(0)
        fulltext_input = copy.deepcopy(data)
        fulltext_input['id'] = None
        data['fulltext'] = self.create_fulltext(fulltext_input)
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "core.personas", data)
            data.update({
                "submitted_by": submitted_by or rs.user.persona_id,
                "generation": 1,
                "change_status": const.MemberChangeStati.committed,
                "persona_id": new_id,
                "change_note": "Account erstellt.",
            })
            # remove unlogged attributes
            del data['password_hash']
            del data['fulltext']
            if not self.conf.CDEDB_OFFLINE_DEPLOYMENT:
                self.sql_insert(rs, "core.changelog", data)
            self.core_log(rs, const.CoreLogCodes.persona_creation, new_id)
        return new_id

    @access("anonymous")
    def login(self, rs, username, password, ip):
        """Create a new session.

        This invalidates all existing sessions for this persona. Sessions
        are bound to an IP-address, for bookkeeping purposes.

        In case of successful login, this updates the request state with a
        new user object and escalates the database connection to reflect the
        non-anonymous access.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type username: str
        :type password: str
        :type ip: str
        :rtype: str or None
        :returns: the session-key for the new session
        """
        username = affirm("printable_ascii", username)
        password = affirm("str", password)
        ip = affirm("printable_ascii", ip)
        # note the lower-casing for email addresses
        query = glue(
            "SELECT id, password_hash, is_admin, is_core_admin",
            "FROM core.personas",
            "WHERE username = lower(%s) AND is_active = True")
        data = self.query_one(rs, query, (username,))
        verified = bool(data) and self.conf.CDEDB_OFFLINE_DEPLOYMENT
        if not verified and data:
            verified = self.verify_password(password, data["password_hash"])
        if not verified:
            # log message to be picked up by fail2ban
            self.logger.warning("CdEDB login failure from {} for {}".format(
                ip, username))
            return None
        else:
            if self.conf.LOCKDOWN and not (data['is_admin']
                                           or data['is_core_admin']):
                # Short circuit in case of lockdown
                return None
            sessionkey = secure_token_hex()

            with Atomizer(rs):
                query = glue(
                    "UPDATE core.sessions SET is_active = False",
                    "WHERE persona_id = %s AND is_active = True")
                self.query_exec(rs, query, (data["id"],))
                query = glue(
                    "INSERT INTO core.sessions (persona_id, ip, sessionkey)",
                    "VALUES (%s, %s, %s)")
                self.query_exec(rs, query, (data["id"], ip, sessionkey))

            # Escalate db privilege role in case of successful login.
            # This will not be deescalated.
            if rs.conn.is_contaminated:
                raise RuntimeError(n_("Atomized – impossible to escalate."))

            is_cde = unwrap(self.sql_select_one(rs, "core.personas",
                                                ("is_cde_realm",), data["id"]))
            if is_cde:
                rs.conn = self.connpool['cdb_member']
            else:
                rs.conn = self.connpool['cdb_persona']
            rs._conn = rs.conn  # Necessary to keep the mechanics happy

            # Get more information about user (for immediate use in frontend)
            data = self.sql_select_one(rs, "core.personas",
                                       PERSONA_CORE_FIELDS, data["id"])
            vals = {k: data[k] for k in (
                'username', 'given_names', 'display_name', 'family_name')}
            vals['persona_id'] = data['id']
            rs.user = User(roles=extract_roles(data), **vals)

            return sessionkey

    @access("persona")
    def logout(self, rs):
        """Invalidate the current session.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: int
        :returns: default return code
        """
        query = glue(
            "UPDATE core.sessions SET is_active = False, atime = now()",
            "WHERE sessionkey = %s AND is_active = True")
        return self.query_exec(rs, query, (rs.sessionkey,))

    @access("persona")
    def verify_ids(self, rs, ids):
        """Check that persona ids do exist.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: bool
        """
        ids = affirm_set("id", ids)
        if ids == {rs.user.persona_id}:
            return True
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE id = ANY(%s)"
        data = self.query_one(rs, query, (ids,))
        return data['num'] == len(ids)

    @internal_access("persona")
    @singularize("get_roles_single")
    def get_roles_multi(self, rs, ids):
        """Resolve ids into roles.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: str}
        :returns: dict mapping id to realm
        """
        if ids == (rs.user.persona_id,):
            return {rs.user.persona_id: rs.user.roles}
        bits = PERSONA_STATUS_FIELDS + ("id",)
        data = self.sql_select(rs, "core.personas", bits, ids)
        return {d['id']: extract_roles(d) for d in data}

    @access("persona")
    @singularize("get_realms_single")
    def get_realms_multi(self, rs, ids):
        """Resolve ids into realms.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: str}
        :returns: dict mapping id to realm
        """
        ids = affirm_set("id", ids)
        roles = self.get_roles_multi(rs, ids)
        all_realms = {"cde", "event", "assembly", "ml"}
        return {key: value & all_realms for key, value in roles.items()}

    @access("persona")
    def verify_personas(self, rs, ids, required_roles=None):
        """Check wether certain ids map to actual personas.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :type required_roles: [str]
        :param required_roles: If given check that all personas have
          these roles.
        :rtype: [int]
        :returns: All ids which successfully validated.
        """
        ids = affirm_set("id", ids)
        required_roles = required_roles or tuple()
        required_roles = affirm_set("str", required_roles)
        roles = self.get_roles_multi(rs, ids)
        return tuple(key for key, value in roles.items()
                     if value >= required_roles)

    @access("anonymous")
    def verify_existence(self, rs, email):
        """Check wether a certain email belongs to any persona.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :rtype: bool
        """
        email = affirm("email", email)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE username = %s"
        data = self.query_one(rs, query, (email,))
        query = glue("SELECT COUNT(*) AS num FROM core.genesis_cases",
                     "WHERE username = %s AND case_status = ANY(%s)")
        # This should be all stati which are not final.
        stati = (const.GenesisStati.unconfirmed,
                 const.GenesisStati.to_review,
                 const.GenesisStati.approved)  # approved is a temporary state.
        data2 = self.query_one(rs, query, (email, stati))
        return bool(data['num'] + data2['num'])

    RESET_COOKIE_PAYLOAD = "X"

    def _generate_reset_cookie(self, rs, persona_id, salt,
                               timeout=datetime.timedelta(seconds=60)):
        """Create a cookie which authorizes a specific reset action.

        The cookie depends on the inputs as well as a server side secret.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type salt: str
        :type timeout: datetime.timedelta
        :rtype: str
        """
        with Atomizer(rs):
            if not self.is_admin(rs):
                roles = unwrap(self.get_roles_multi(rs, (persona_id,)))
                if any("admin" in role for role in roles):
                    raise PrivilegeError(n_("Preventing reset of admin."))
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            # This uses the encode_parameter function in a somewhat sloppy
            # manner, but the security guarantees still keep
            cookie = encode_parameter(
                salt, persona_id, password_hash, self.RESET_COOKIE_PAYLOAD,
                timeout=timeout)
            return cookie

    def _verify_reset_cookie(self, rs, persona_id, salt, cookie):
        """Check a provided cookie for correctness.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type cookie: str
        :type salt: str
        :rtype: bool, str
        """
        with Atomizer(rs):
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            timeout, msg = decode_parameter(salt, persona_id, password_hash,
                                            cookie)
            if msg is None:
                if timeout:
                    return False, n_("Link expired.")
                else:
                    return False, n_("Link invalid or already used.")
            if msg != self.RESET_COOKIE_PAYLOAD:
                return False, n_("Link invalid or already used.")
            return True, None

    def modify_password(self, rs, new_password, old_password=None,
                        reset_cookie=None, persona_id=None):
        """Helper for manipulating password entries.

        The persona_id parameter is only for the password reset case. We
        intentionally only allow to change the own password.

        An authorization must be provided, either by ``old_password`` or
        ``reset_cookie``.

        This escalates database connection privileges in the case of a
        password reset (which is by its nature anonymous).

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type new_password: str
        :type old_password: str or None
        :type reset_cookie: str or None
        :type persona_id: int or None
        :param persona_id: Must be provided only in case of reset.
        :returns: The ``bool`` indicates success and the ``str`` is
          either the new password or an error message.
        :rtype: (bool, str)
        """
        if persona_id and not reset_cookie:
            return False, n_("Selecting persona allowed for reset only.")
        persona_id = persona_id or rs.user.persona_id
        if not persona_id:
            return False, n_("Could not determine persona to reset.")
        if not old_password and not reset_cookie:
            return False, n_("No authorization provided.")
        if old_password:
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            if not self.verify_password(old_password, password_hash):
                return False, n_("Password verification failed.")
        if reset_cookie:
            success, msg = self.verify_reset_cookie(
                rs, persona_id, reset_cookie)
            if not success:
                return False, msg
        if not new_password:
            return False, n_("No new password provided.")
        if not validate.is_password_strength(new_password):
            return False, n_("Password too weak.")
        # escalate db privilege role in case of resetting passwords
        orig_conn = None
        try:
            if reset_cookie and "persona" not in rs.user.roles:
                if rs.conn.is_contaminated:
                    raise RuntimeError(
                        n_("Atomized – impossible to escalate."))
                orig_conn = rs.conn
                rs.conn = self.connpool['cdb_persona']
            # do not use set_persona since it doesn't operate on password
            # hashes by design
            query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
            with rs.conn as conn:
                with conn.cursor() as cur:
                    self.execute_db_query(
                        cur, query,
                        (self.encrypt_password(new_password), persona_id))
                    ret = cur.rowcount
        finally:
            # deescalate
            if orig_conn:
                rs.conn = orig_conn
        return ret, new_password

    @access("persona")
    def change_password(self, rs, old_password, new_password):
        """
        :type rs: :py:class:`cdedb.common.RequestState`
        :type old_password: str
        :type new_password: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        old_password = affirm("str", old_password)
        new_password = affirm("str", new_password)
        ret = self.modify_password(rs, new_password, old_password=old_password)
        self.core_log(rs, const.CoreLogCodes.password_change,
                      rs.user.persona_id)
        return ret

    @access("anonymous")
    def check_password_strength(self, rs, password, *, email=None,
                                persona_id=None, argname=None):
        """Check the password strength using some additional userdate.

        This escalates database connection privileges in the case of an
        anonymous request, that is for a password reset.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type password: str
        :type email: str or None
        :type persona_id: int or None
        :type argname: str or None
        :rtype: str
        """
        password = affirm("str", password)
        email = affirm("str_or_None", email)
        persona_id = affirm("id_or_None", persona_id)
        argname = affirm("str_or_None", argname)

        if email is None and persona_id is None:
            raise ValueError(n_("No input provided."))
        elif email and persona_id:
            raise ValueError(n_("More than one input provided."))
        if email:
            persona_id = unwrap(self.sql_select_one(
                rs, "core.personas", ("id",), email, entity_key="username"))

        columns_of_interest = [
            "is_cde_realm", "is_admin", "is_core_admin", "is_cde_admin",
            "is_event_admin", "is_ml_admin", "is_assembly_admin", "username",
            "given_names", "family_name", "display_name", "title",
            "name_supplement", "birthday"]

        # escalate db privilege role in case of resetting passwords
        orig_conn = None
        try:
            if "persona" not in rs.user.roles:
                if rs.conn.is_contaminated:
                    raise RuntimeError(
                        n_("Atomized – impossible to escalate."))
                orig_conn = rs.conn
                rs.conn = self.connpool['cdb_persona']
            persona = self.sql_select_one(
                rs, "core.personas", columns_of_interest, persona_id)
        finally:
            # deescalate
            if orig_conn:
                rs.conn = orig_conn

        admin = any(persona[admin] for admin in
                    ("is_admin", "is_core_admin", "is_cde_admin",
                     "is_event_admin", "is_ml_admin", "is_assembly_admin"))
        inputs = (persona['username'].split('@') +
                  persona['given_names'].replace('-', ' ').split() +
                  persona['family_name'].replace('-', ' ').split() +
                  persona['display_name'].replace('-', ' ').split())
        if persona['title']:
            inputs.extend(persona['title'].replace('-', ' ').split())
        if persona['name_supplement']:
            inputs.extend(persona['name_supplement'].replace('-', ' ').split())
        if persona['birthday']:
            inputs.extend(persona['birthday'].isoformat().split('-'))

        password, errs = validate.check_password_strength(
            password, argname, admin=admin, inputs=inputs)

        return password, errs

    @access("anonymous")
    def make_reset_cookie(self, rs, email, timeout=None):
        """Perform preparation for a recovery.

        This generates a reset cookie which can be used in a second step
        to actually reset the password. To reset the password for a
        privileged account you need to have privileges yourself.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :type timeout: datetime.timedelta or None
        :rtype: (bool, str)
        :returns: The ``bool`` indicates success and the ``str`` is
          either the reset cookie or an error message.
        """
        timeout = timeout or self.conf.PARAMETER_TIMEOUT
        email = affirm("email", email)
        data = self.sql_select_one(rs, "core.personas", ("id", "is_active"),
                                   email, entity_key="username")
        if not data:
            return False, n_("Nonexistant user.")
        if not data['is_active']:
            return False, n_("Inactive user.")
        ret = self.generate_reset_cookie(rs, data['id'], timeout=timeout)
        self.core_log(rs, const.CoreLogCodes.password_reset_cookie, data['id'])
        return True, ret

    @access("anonymous")
    def reset_password(self, rs, email, new_password, cookie):
        """Perform a recovery.

        Authorization is guaranteed by the cookie.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :type new_password: str
        :type cookie: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        email = affirm("email", email)
        new_password = affirm("str", new_password)
        cookie = affirm("str", cookie)
        data = self.sql_select_one(rs, "core.personas", ("id",), email,
                                   entity_key="username")
        if not data:
            return False, n_("Nonexistant user.")
        if self.conf.LOCKDOWN:
            return False, n_("Lockdown active.")
        persona_id = unwrap(data)
        success, msg = self.modify_password(
            rs, new_password, reset_cookie=cookie, persona_id=persona_id)
        if success:
            self.core_log(rs, const.CoreLogCodes.password_reset, persona_id)
        return success, msg

    @access("anonymous")
    def genesis_request(self, rs, data):
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new request or None if the username is already
          taken
        """
        data = affirm("genesis_case", data, creation=True)
        if self.verify_existence(rs, data['username']):
            return None
        if self.conf.LOCKDOWN and not self.is_admin(rs):
            return None
        data['case_status'] = const.GenesisStati.unconfirmed
        ret = self.sql_insert(rs, "core.genesis_cases", data)
        self.core_log(rs, const.CoreLogCodes.genesis_request, persona_id=None,
                      additional_info=data['username'])
        return ret

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def delete_genesis_case_blockers(self, rs, case_id):
        """Determine what keeps a genesis case from being deleted.

        Possible blockers:

        * unconfirmed: A genesis case with status unconfirmed may only be
                       deleted after the timeout period has passed.
        * case_status: A genesis case may not be deleted if it has one of the
                       following stati: to_review, approved.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """

        case_id = affirm("id", case_id)
        blockers = {}

        case = self.genesis_get_case(rs, case_id)
        if (case["case_status"] == const.GenesisStati.unconfirmed and
                now() < case["ctime"] + self.conf.PARAMETER_TIMEOUT):
            blockers["unconfirmed"] = case_id
        if case["case_status"] in {const.GenesisStati.to_review,
                                   const.GenesisStati.approved}:
            blockers["case_status"] = case["case_status"]

        return blockers

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def delete_genesis_case(self, rs, case_id, cascade=None):
        """Remove a genesis case."""

        case_id = affirm("id", case_id)
        blockers = self.delete_genesis_case_blockers(rs, case_id)
        if "unconfirmed" in blockers.keys():
            raise ValueError(n_("Unable to remove unconfirmed genesis case "
                                "before confirmation timeout."))
        if "case_status" in blockers.keys():
            raise ValueError(n_("Unable to remove genesis case with status {}.")
                             .format(blockers["case_status"]))
        if not cascade:
            cascade = set()
        cascade = affirm_set("str", cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "genesis case",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            if cascade:
                if "unconfirmed" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "unconfirmed"})
                if "case_status" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "case_status"})

            if not blockers:
                ret *= self.sql_delete_one(rs, "core.genesis_cases", case_id)
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})

        return ret

    @access("anonymous")
    def genesis_case_by_email(self, rs, email):
        """Get the id of an unconfirmed genesis case for a given email.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :rtype: int or None
        :returns: The case id or None if no such case exists.
        """
        email = affirm("str", email)
        query = glue("SELECT id FROM core.genesis_cases",
                     "WHERE username = %s AND case_status = %s")
        params = (email, const.GenesisStati.unconfirmed)
        data = self.query_one(rs, query, params)
        return unwrap(data) if data else None
    
    @access("anonymous")
    def genesis_verify(self, rs, case_id):
        """Confirm the new email address and proceed to the next stage.

        Returning the realm is a conflation caused by lazyness, but before
        we create another function bloating the code this will do.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :rtype: (int, str or None)
        :returns: (default return code, realm of the case if successful)

        """
        case_id = affirm("id", case_id)
        query = glue("UPDATE core.genesis_cases SET case_status = %s",
                     "WHERE id = %s AND case_status = %s")
        params = (const.GenesisStati.to_review, case_id,
                  const.GenesisStati.unconfirmed)
        ret = self.query_exec(rs, query, params)
        realm = None
        if ret > 0:
            realm = unwrap(self.sql_select_one(
                rs, "core.genesis_cases", ("realm",), case_id))
        return ret, realm

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis_list_cases(self, rs, realms=None, stati=None):
        """List persona creation cases.

        Restrict to certain stati and certain target realms.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type stati: {int} or None
        :param stati: restrict to these stati
        :type realms: [str] or None
        :param realms: restrict to these realms
        :rtype: {int: {str: object}}
        :returns: dict mapping case ids to dicts containing information
          about the case
        """
        realms = realms or []
        realms = affirm_set("str", realms)
        stati = stati or set()
        stati = affirm_set("enum_genesisstati", stati)
        if not realms and "core_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Not privileged."))
        elif not all({"{}_admin".format(realm), "core_admin"} & rs.user.roles
                     for realm in realms):
            raise PrivilegeError(n_("Not privileged."))
        query = glue("SELECT id, ctime, username, given_names, family_name,",
                     "case_status FROM core.genesis_cases")
        connector = " WHERE"
        params = []
        if realms:
            query = glue(query, connector, "realm = ANY(%s)")
            params.append(realms)
            connector = "AND"
        if stati:
            query = glue(query, connector, "case_status = ANY(%s)")
            params.append(stati)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    @singularize("genesis_get_case")
    def genesis_get_cases(self, rs, ids):
        """Retrieve datasets for persona creation cases.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to the requested data
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "core.genesis_cases", GENESIS_CASE_FIELDS,
                               ids)
        if ("core_admin" not in rs.user.roles
                and any("{}_admin".format(e['realm']) not in rs.user.roles
                        for e in data)):
            raise PrivilegeError(n_("Not privileged."))
        return {e['id']: e for e in data}

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis_modify_case(self, rs, data):
        """Modify a persona creation case.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("genesis_case", data)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "core.genesis_cases", ("case_status", "username", "realm"),
                data['id'])
            if not ({"core_admin", "{}_admin".format(current['realm'])}
                    & rs.user.roles):
                raise PrivilegeError(n_("Not privileged."))
            if ('realm' in data
                    and not ({"core_admin", "{}_admin".format(data['realm'])}
                             & rs.user.roles)):
                raise PrivilegeError(n_("Not privileged."))
            ret = self.sql_update(rs, "core.genesis_cases", data)
        if (data.get('case_status')
                and data['case_status'] != current['case_status']):
            if data['case_status'] == const.GenesisStati.approved:
                self.core_log(
                    rs, const.CoreLogCodes.genesis_approved, persona_id=None,
                    additional_info=current['username'])
            elif data['case_status'] == const.GenesisStati.rejected:
                self.core_log(
                    rs, const.CoreLogCodes.genesis_rejected, persona_id=None,
                    additional_info=current['username'])
        return ret

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis(self, rs, case_id):
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :rtype: int
        :returns: The id of the newly created persona.
        """
        case_id = affirm("id", case_id)
        ACCESS_BITS = {
            'event': {
                'is_cde_realm': False,
                'is_event_realm': True,
                'is_assembly_realm': False,
                'is_ml_realm': True,
                'is_member': False,
                'is_searchable': False,
            },
            'ml': {
                'is_cde_realm': False,
                'is_event_realm': False,
                'is_assembly_realm': False,
                'is_ml_realm': True,
                'is_member': False,
                'is_searchable': False,
            },
        }
        with Atomizer(rs):
            case = unwrap(self.genesis_get_cases(rs, (case_id,)))
            data = {k: v for k, v in case.items()
                    if k in PERSONA_ALL_FIELDS and k != "id"}
            data['display_name'] = data['given_names']
            merge_dicts(data, PERSONA_DEFAULTS)
            # Fix realms, so that the persona validator does the correct thing
            data.update(ACCESS_BITS[case['realm']])
            data = affirm("persona", data, creation=True)
            if case['case_status'] != const.GenesisStati.approved:
                raise ValueError(n_("Invalid genesis state."))
            roles = extract_roles(data)
            if extract_realms(roles) != \
                    ({case['realm']} | implied_realms(case['realm'])):
                raise PrivilegeError(n_("Wrong target realm."))
            ret = self.create_persona(
                rs, data, submitted_by=case['reviewer'])
            update = {
                'id': case_id,
                'case_status': const.GenesisStati.successful,
            }
            self.sql_update(rs, "core.genesis_cases", update)
            return ret

    @access("core_admin")
    def find_doppelgangers(self, rs, persona):
        """Look for accounts with data similar to the passed dataset.

        This is for batch admission, where we may encounter datasets to
        already existing accounts. In that case we do not want to create
        a new account.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona: {str: object}
        :rtype: {int: {str: object}}
        :returns: A dict of possibly matching account data.
        """
        persona = affirm("persona", persona)
        scores = collections.defaultdict(lambda: 0)
        queries = (
            (10, "given_names = %s OR display_name = %s",
             (persona['given_names'], persona['given_names'])),
            (10, "family_name = %s OR birth_name = %s",
             (persona['family_name'], persona['family_name'])),
            (10, "family_name = %s OR birth_name = %s",
             (persona['birth_name'], persona['birth_name'])),
            (10, "birthday = %s", (persona['birthday'],)),
            (5, "location = %s", (persona['location'],)),
            (5, "postal_code = %s", (persona['postal_code'],)),
            (20, "given_names = %s AND family_name = %s",
             (persona['family_name'], persona['given_names'],)),
            (21, "username = %s", (persona['username'],)),)
        # Omit queries where some parameters are None
        queries = tuple(e for e in queries if all(x is not None for x in e[2]))
        for score, condition, params in queries:
            query = "SELECT id FROM core.personas WHERE {}".format(condition)
            result = self.query_all(rs, query, params)
            for e in result:
                scores[unwrap(e)] += score
        CUTOFF = 21
        MAX_ENTRIES = 7
        persona_ids = tuple(k for k, v in scores.items() if v > CUTOFF)
        persona_ids = sorted(persona_ids, key=lambda k: -scores.get(k))
        persona_ids = persona_ids[:MAX_ENTRIES]
        return self.get_total_personas(rs, persona_ids)

    @access("anonymous")
    def get_meta_info(self, rs):
        """Retrieve changing info about the DB and the CdE e.V.

        This is a relatively painless way to specify lots of constants
        like who is responsible for donation certificates.

        :type rs: :py:class:`cdedb.common.RequestState`
        :rtype: {str: str}
        """
        query = "SELECT info FROM core.meta_info LIMIT 1"
        return unwrap(self.query_one(rs, query, tuple()))

    @access("core_admin")
    def set_meta_info(self, rs, data):
        """Change infos about the DB and the CdE e.V.

        This is expected to occur regularly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: str}
        :rtype: int
        :returns: Standard return code.
        """
        with Atomizer(rs):
            meta_info = self.get_meta_info(rs)
            # Late validation since we need to know the keys
            data = affirm("meta_info", data, keys=meta_info.keys())
            meta_info.update(data)
            query = "UPDATE core.meta_info SET info = %s"
            return self.query_exec(rs, query, (PsycoJson(meta_info),))

    @access("core_admin")
    def get_cron_store(self, rs, name):
        """Retrieve the persistent store of a cron job.

        If no entry exists, an empty dict ist returned.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type name: str
        :param name: name of the cron job
        :rtype: {str: object}
        """
        ret = self.sql_select_one(rs, "core.cron_store", ("store",),
                                  name, entity_key="moniker")
        if ret:
            ret = unwrap(ret)
        else:
            ret = {}
        return ret

    @access("core_admin")
    def set_cron_store(self, rs, name, data):
        """Update the store of a cron job.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type name: str
        :rtype: int
        :returns: Standard return code.
        """
        update = {
            'moniker': name,
            'store': PsycoJson(data),
        }
        with Atomizer(rs):
            ret = self.sql_update(rs, "core.cron_store", update,
                                  entity_key='moniker')
            if not ret:
                ret = self.sql_insert(rs, "core.cron_store", update)
            return ret

    @access("core_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("query", query)
        if query.scope == "qview_core_user":
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_archived"] = "bool"
        elif query.scope == "qview_archived_persona":
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      True))
            query.spec["is_archived"] = "bool"
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)

    @access("persona")
    def submit_select_persona_query(self, rs, query):
        """Accessible version of :py:meth:`submit_general_query`.

        This should be used solely by the persona select API which is also
        accessed by less privileged accounts. The frontend takes the
        necessary precautions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]

        """
        return self.submit_general_query(rs, query)
