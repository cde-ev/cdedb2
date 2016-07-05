#!/usr/bin/env python3

"""The core backend provides services which are common for all
users/personas independent of their realm. Thus we have no user role
since the basic division is between known accounts and anonymous
accesses.
"""
import collections
import copy
import decimal
import hashlib
import random
import subprocess
import tempfile
import uuid

import ldap3
from passlib.hash import sha512_crypt
import psycopg2.extras

from cdedb.backend.common import AbstractBackend
from cdedb.backend.common import (
    access, internal_access, singularize,
    affirm_validation as affirm, affirm_array_validation as affirm_array)
from cdedb.common import (
    glue, GENESIS_CASE_FIELDS, PrivilegeError, unwrap, extract_roles,
    PERSONA_CORE_FIELDS, PERSONA_CDE_FIELDS, PERSONA_EVENT_FIELDS,
    PERSONA_ASSEMBLY_FIELDS, PERSONA_ML_FIELDS, PERSONA_ALL_FIELDS,
    privilege_tier, now, QuotaException, PERSONA_STATUS_FIELDS)
from cdedb.config import SecretsConfig
from cdedb.database.connection import Atomizer
import cdedb.validation as validate
import cdedb.database.constants as const
from cdedb.query import QueryOperators
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory

def ldap_bool(val):
    """Convert a :py:class:`bool` to its LDAP representation.

    :type val: bool
    :rtype: str
    """
    mapping = {
        True: 'TRUE',
        False: 'FALSE',
    }
    return mapping[val]

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
            secrets)
        self.ldap_server = ldap3.Server(self.conf.LDAP_URL)
        self.ldap_connect = lambda: ldap3.Connection(
            self.ldap_server, self.conf.LDAP_USER, secrets.LDAP_PASSWORD)
        self.generate_reset_cookie = (
            lambda rs, persona_id: self._generate_reset_cookie(
                rs, persona_id, secrets.RESET_SALT))
        self.verify_reset_cookie = (
            lambda rs, persona_id, cookie: self._verify_reset_cookie(
                rs, persona_id, secrets.RESET_SALT, cookie))

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

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
        return sha512_crypt.encrypt(password)

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
        ## do not use sql_insert since it throws an error for selecting the id
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
    def retrieve_log(self, rs, codes=None, persona_id=None, start=None,
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
            rs, "enum_corelogcodes", "persona", "core.log", codes, persona_id,
            start, stop)

    @access("core_admin")
    def retrieve_changelog_meta(self, rs, stati=None, start=None, stop=None):
        """Get changelog activity.

        Similar to
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
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
            ## check for race
            current_generation = unwrap(self.changelog_get_generations(
                rs, (data['id'],)))
            if generation is not None and current_generation != generation:
                self.logger.info("Generation mismatch {} != {} for {}".format(
                    current_generation, generation, data['id']))
                return 0

            ## get current state
            history = self.changelog_get_history(
                rs, data['id'], generations=(current_generation,))
            current_data = history[current_generation]

            ## handle pending changes
            diff = None
            if current_data['change_status'] == const.MemberChangeStati.pending:
                committed_data = unwrap(self.get_total_personas(
                    rs, (data['id'],)))
                ## stash pending change if we may not wait
                if not may_wait:
                    diff = {key: current_data[key] for key in committed_data
                            if committed_data[key] != current_data[key]}
                    current_data.update(committed_data)
                    query = glue("UPDATE core.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND change_status = %s")
                    self.query_exec(rs, query, (
                        const.MemberChangeStati.displaced, data['id'],
                        const.MemberChangeStati.pending))
            else:
                committed_data = current_data

            ## determine if something changed
            newly_changed_fields = {key for key, value in data.items()
                                    if value != current_data[key]}
            if not newly_changed_fields:
                if diff:
                    ## reenable old change if we were going to displace it
                    query = glue("UPDATE core.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND generation = %s")
                    self.query_exec(rs, query, (const.MemberChangeStati.pending,
                                                data['id'], current_generation))
                return 0

            ## Determine if something requiring a review changed.
            fields_requiring_review = {'birthday', 'family_name', 'given_names'}
            all_changed_fields = {key for key, value in data.items()
                                  if value != committed_data[key]}
            requires_review = (
                (all_changed_fields & fields_requiring_review
                 or (current_data['change_status']
                     == const.MemberChangeStati.pending and not diff))
                and current_data['is_cde_realm']
                and not ({"core_admin", "cde_admin"} & rs.user.roles))

            ## prepare for inserting a new changelog entry
            query = glue("SELECT COUNT(*) AS num FROM core.changelog",
                         "WHERE persona_id = %s")
            next_generation = unwrap(self.query_one(
                rs, query, (data['id'],))) + 1
            ## the following is a nop, if there is no pending change
            query = glue("UPDATE core.changelog SET change_status = %s",
                         "WHERE persona_id = %s AND change_status = %s")
            self.query_exec(rs, query, (
                const.MemberChangeStati.superseded, data['id'],
                const.MemberChangeStati.pending))

            ## insert new changelog entry
            insert = copy.deepcopy(current_data)
            insert.update(data)
            insert.update({
                "submitted_by": rs.user.persona_id,
                "generation": next_generation,
                "change_status": const.MemberChangeStati.pending,
                "persona_id": data['id'],
                "change_note": change_note,
            })
            del insert['id']
            if 'ctime' in insert:
                del insert['ctime']
            self.sql_insert(rs, "core.changelog", insert)

            ## resolve change if it doesn't require review
            if not requires_review:
                ret = self.changelog_resolve_change(
                    rs, data['id'], next_generation, ack=True, reviewed=False)
            else:
                ret = -1
            if not may_wait and ret <= 0:
                raise RuntimeError("Non-waiting change not committed.")

            ## pop the stashed change
            if diff:
                if set(diff) & newly_changed_fields:
                    raise RuntimeError("Conflicting pending change.")
                insert = copy.deepcopy(current_data)
                insert.update(data)
                insert.update(diff)
                insert.update({
                    "submitted_by": rs.user.persona_id,
                    "generation": next_generation + 1,
                    "change_status": const.MemberChangeStati.pending,
                    "persona_id": data['id'],
                    "change_note": "Displaced change.",
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
            self.query_exec(rs, query, (
                rs.user.persona_id, const.MemberChangeStati.nacked, persona_id,
                const.MemberChangeStati.pending, generation))
            return 0
        with Atomizer(rs):
            ## look up changelog entry and mark as committed
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

            ## determine changed fields
            old_data = unwrap(self.get_total_personas(rs, (persona_id,)))
            relevant_keys = tuple(key for key in old_data
                                  if data[key] != old_data[key])
            relevant_keys += ('id',)

            udata = {key: data[key] for key in relevant_keys}
            ## commit changes
            ret = 0
            if len(udata) > 1:
                ret = self.commit_persona(rs, udata,
                                          change_note="Change committed.")
                if not ret:
                    raise RuntimeError("Modification failed.")
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
        stati = affirm_array("enum_memberchangestati", stati)
        query = glue("SELECT persona_id, given_names, family_name, generation",
                     "FROM core.changelog WHERE change_status = ANY(%s)")
        data = self.query_all(rs, query, (stati,))
        return {e['persona_id']: e for e in data}

    @access("persona")
    def changelog_get_history(self, rs, anid, generations):
        """Retrieve history of a data set.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type anid: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int: {str: object}}
        :returns: mapping generation to data set
        """
        anid = affirm("id", anid)
        if anid != rs.user.persona_id and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        generations = affirm_array("int", generations, allow_None=True)
        fields = list(PERSONA_ALL_FIELDS)
        fields.remove('id')
        fields.append("persona_id AS id")
        fields.extend(("submitted_by", "reviewed_by", "ctime", "generation",
                       "change_status", "change_note"))
        query = "SELECT {} FROM core.changelog WHERE persona_id = %s".format(
            ", ".join(fields))
        params = [anid]
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
        actually modifies the core.personas table. Here we also take
        care of keeping the ldap store in sync with the database.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type change_note: str or None
        :rtype int:
        :returns: standard return code
        """
        ldap_ops = {}
        if 'username' in data:
            ldap_ops['mail'] = [(ldap3.MODIFY_REPLACE, [data['username']])]
        if 'given_names' in data:
            ldap_ops['cn'] = [(ldap3.MODIFY_REPLACE, [data['given_names']])]
        if 'family_name' in data:
            ldap_ops['sn'] = [(ldap3.MODIFY_REPLACE, [data['family_name']])]
        if 'display_name' in data:
            ldap_ops['displayName'] = [(ldap3.MODIFY_REPLACE,
                                        [data['display_name']])]
        if 'cloud_account' in data:
            ldap_ops['cloudAccount'] = [(ldap3.MODIFY_REPLACE,
                                         [ldap_bool(data['cloud_account'])])]
        if 'is_active' in data:
            ldap_ops['isActive'] = [(ldap3.MODIFY_REPLACE,
                                     [ldap_bool(data['is_active'])])]
        dn = "uid={},{}".format(data['id'], self.conf.LDAP_UNIT_NAME)
        ## Atomize so that ldap and postgres do not diverge.
        with Atomizer(rs):
            num = self.sql_update(rs, "core.personas", data)
            if not num:
                raise ValueError("Nonexistant user.")
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
            if ldap_ops:
                with self.ldap_connect() as l:
                    l.modify(dn, ldap_ops)
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
            self.logger.info("No change note specified (persona_id={}).".format(
                data['id']))
            change_note = "Unspecified change."

        if not may_wait and generation is not None:
            raise ValueError("Non-waiting change without generation override.")
        realm_keys = {'is_cde_realm', 'is_event_realm', 'is_ml_realm',
                      'is_assembly_realm'}
        if (set(data) & realm_keys
                and (not (rs.user.roles & {"core_admin", "admin"})
                     or "realms" not in allow_specials)):
            raise PrivilegeError("Realm modification prevented.")
        admin_keys = {'is_cde_admin', 'is_event_admin', 'is_ml_admin',
                      'is_assembly_admin', 'is_core_admin', 'is_admin'}
        if (set(data) & admin_keys
                and ("admin" not in rs.user.roles
                     or "admins" not in allow_specials)):
            raise PrivilegeError("Admin privelege modification prevented.")
        if ("is_member" in data
                and (not ({"cde_admin", "core_admin"} & rs.user.roles)
                     or "membership" not in allow_specials)):
            raise PrivilegeError("Membership modification prevented.")
        if (not data.get("is_searchable", True)
                and (not ({"cde_admin", "core_admin"} & rs.user.roles))):
            raise PrivilegeError("Hiding prevented.")
        if ("is_archived" in data
                and ("core_admin" not in rs.user.roles
                     or "archive" not in allow_specials)):
            raise PrivilegeError("Archive modification prevented.")
        if ("balance" in data
                and ("cde_admin" not in rs.user.roles
                     or "finance" not in allow_specials)):
            raise PrivilegeError("Modification of balance prevented.")
        if "username" in data and "username" not in allow_specials:
            raise PrivilegeError("Modification of username prevented.")
        if "foto" in data and "foto" not in allow_specials:
            raise PrivilegeError("Modification of foto prevented.")
        if ("cloud_account" in data
                and not ({"core_admin", "cde_admin"} & rs.user.roles)):
            raise PrivilegeError("Modification of cloud access prevented.")
        if data.get("is_active") and rs.user.persona_id == data['id']:
            raise PrivilegeError("Own activation prevented.")

        ## check for permission to edit
        is_archived = None
        if rs.user.persona_id != data['id']:
            privs = self.sql_select_one(rs, "core.personas",
                                        PERSONA_STATUS_FIELDS, data['id'])
            if not privilege_tier(extract_roles(privs)) & rs.user.roles:
                raise PrivilegeError("Not privileged.")
            is_archived = privs['is_archived'] ## store for later use

        ## Prevent modification of archived members. This check (using
        ## is_archived) is sufficient since we can only edit our own data if
        ## we are not archived.
        if is_archived and data.get('is_archived', True):
            raise RuntimeError("Editing archived member impossible.")

        with Atomizer(rs):
            ## reroute through the changelog if necessary
            if (not self.conf.CDEDB_OFFLINE_DEPLOYMENT
                    and "archive" not in allow_specials):
                ret = self.changelog_submit_change(
                    rs, data, generation=generation,
                    may_wait=may_wait, change_note=change_note)
                if allow_specials and ret < 0:
                    raise RuntimeError("Special change not committed.")
                return ret

            return self.commit_persona(rs, data, change_note)

    @access("persona")
    def change_persona(self, rs, data, generation=None, may_wait=True,
                       change_note=None):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
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
                ## Fix balance
                tmp = unwrap(self.get_total_personas(rs, (data['id'],)))
                if tmp['balance'] is None:
                    data['balance'] = decimal.Decimal('0.0')
                else:
                    data['balance'] = tmp['balance']
            return self.set_persona(
                rs, data, may_wait=False, change_note="Realms modified.",
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
            rs, data, may_wait=False, change_note="Foto modified.",
            allow_specials=("foto",))

    @access("admin")
    def change_admin_bits(self, rs, data):
        """Special modification function for privileges.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("persona", data)
        return self.set_persona(
            rs, data, may_wait=False, change_note="Admin bits modified.",
            allow_specials=("admins",))

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
        balance = affirm("decimal", balance)
        log_code = affirm("enum_financelogcodes", log_code)
        change_note = affirm("str_or_None", change_note)
        update = {
            'id': persona_id,
            'balance': balance,
        }
        with Atomizer(rs):
            current = unwrap(self.retrieve_personas(rs, (persona_id,),
                                                    ("balance",)))
            if current['balance'] != balance:
                ret = self.set_persona(
                    rs, update, may_wait=False, change_note=change_note,
                    allow_specials=("finance",))
                self.finance_log(rs, log_code, persona_id,
                                 balance - current['balance'], balance)
                return ret

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
                raise RuntimeError("Not a CdE-Account.")
            if current['is_member'] == is_member:
                return 0
            if not is_member:
                delta = -current['balance']
                new_balance = decimal.Decimal(0)
                code = const.FinanceLogCodes.lose_membership
                update['is_searchable'] = False
                update['decided_search'] = False
                update['balance'] = decimal.Decimal(0)
            else:
                delta = None
                new_balance = None
                code = const.FinanceLogCodes.gain_membership
            ret = self.set_persona(
                rs, update, may_wait=False, change_note="Membership change.",
                allow_specials=("membership", "finance"))
            self.finance_log(rs, code, persona_id, delta, new_balance)
            return ret

    @access("core_admin")
    def archive_persona(self, rs, persona_id):
        """TODO"""
        raise NotImplementedError("To be done.")

    @access("core_admin")
    def dearchive_persona(self, rs, persona_id):
        """TODO"""
        raise NotImplementedError("To be done.")

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
        if new_username is None and not self.is_admin(rs):
            return False, "Only admins may unset a username."
        with Atomizer(rs):
            if new_username and self.verify_existence(rs, new_username):
                ## abort if there is already an account with this address
                return False, "Name collision."
            authorized = False
            if self.is_admin(rs):
                authorized = True
            elif password:
                data = self.sql_select_one(rs, "core.personas",
                                           ("password_hash",), persona_id)
                if data and self.verify_password(password, unwrap(data)):
                    authorized = True
            if authorized:
                new_data = {
                    'id': persona_id,
                    'username': new_username,
                }
                change_note = "Username change."
                if self.set_persona(
                        rs, new_data, change_note=change_note, may_wait=False,
                        allow_specials=("username",)):
                    return True, new_username
        return False, "Failed."

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
        ids = affirm_array("id", ids)
        return self.retrieve_personas(rs, ids, columns=PERSONA_CORE_FIELDS)

    @access("event")
    @singularize("get_event_user")
    def get_event_users(self, rs, ids):
        """Get an event view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_EVENT_FIELDS)
        if (ids != (rs.user.persona_id,)
                and "event_admin" not in rs.user.roles
                and (any(e['is_cde_realm'] for e in ret.values()))):
            ## The event user view on a cde user contains lots of personal
            ## data. So we require the requesting user to be orga if (s)he
            ## wants to view it.
            ##
            ## This is a bit of a transgression since we access the event
            ## schema from the core backend, but we go for security instead of
            ## correctness here.
            query = "SELECT event_id FROM event.orgas WHERE persona_id = %s"
            if not self.query_all(rs, query, (rs.user.persona_id,)):
                raise PrivilegeError("Access to CdE data sets inhibited.")
        if any(not e['is_event_realm'] for e in ret.values()):
            raise RuntimeError("Not an event user.")
        return ret

    @access("cde")
    @singularize("get_cde_user")
    def get_cde_users(self, rs, ids):
        """Get an cde view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
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
                    and not {"cde_admin", "core_admin"} & rs.user.roles):
                raise QuotaException("Too many queries.")
            if new:
                self.query_exec(rs, query,
                                (num + new, rs.user.persona_id, today))
            ret = self.retrieve_personas(rs, ids, columns=PERSONA_CDE_FIELDS)
            if any(not e['is_cde_realm'] for e in ret.values()):
                raise RuntimeError("Not a CdE user.")
            if (not {"searchable", "cde_admin", "core_adimn"} & rs.user.roles
                    and any(
                        e['id'] != rs.user.persona_id and not e['is_searchable']
                        for e in ret.values())):
                raise RuntimeError("Improper access to member data.")
            return ret

    @access("ml")
    @singularize("get_ml_user")
    def get_ml_users(self, rs, ids):
        """Get an ml view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_ML_FIELDS)
        if any(not e['is_ml_realm'] for e in ret.values()):
            raise RuntimeError("Not an ml user.")
        return ret

    @access("assembly")
    @singularize("get_assembly_user")
    def get_assembly_users(self, rs, ids):
        """Get an assembly view on some data sets.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("id", ids)
        ret = self.retrieve_personas(rs, ids, columns=PERSONA_ASSEMBLY_FIELDS)
        if any(not e['is_assembly_realm'] for e in ret.values()):
            raise RuntimeError("Not an assembly user.")
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
        ids = affirm_array("id", ids)
        if ids != (rs.user.persona_id,) and not self.is_admin(rs):
            raise PrivilegeError("Must be privileged.")
        return self.retrieve_personas(rs, ids, columns=PERSONA_ALL_FIELDS)

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def create_persona(self, rs, data, submitted_by=None):
        """Instantiate a new data set.

        This does the house-keeping and inserts corresponding entries in
        the changelog and the ldap service.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type submitted_by: int or None
        :param submitted_by: Allow to override the submitter for genesis.
        :rtype: int
        :returns: The id of the newly created persona.
        """
        data = affirm("persona", data, creation=True)
        ## zap any admin attempts
        data.update({
            'is_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
        })
        tier = privilege_tier(extract_roles(data))
        if not (tier & rs.user.roles):
            raise PrivilegeError("Unable to create this sort of persona.")
        ## modified version of hash for 'secret' and thus safe/unknown plaintext
        data['password_hash'] = glue(
            "$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/",
            "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHE/si/")
        ## add balance for cde users
        if data.get('is_cde_realm') and 'balance' not in data:
            data['balance'] = decimal.Decimal(0)
        fulltext_data = copy.deepcopy(data)
        fulltext_data['id'] = None
        data['fulltext'] = self.create_fulltext(fulltext_data)
        attributes = {
            'sn': "({})".format(data['username']),
            'mail': data['username'],
            ## againg slight modification of 'secret'
            'userPassword': "{SSHA}D5JG6KwFxs11jv0LnEmFSeBCjGrHCDWV",
            'cn': data['display_name'],
            'displayName': data['display_name'],
            'cloudAccount': ldap_bool(data['cloud_account']),
            'isActive': ldap_bool(data['is_active'])}
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "core.personas", data)
            data.update({
                "submitted_by": submitted_by or rs.user.persona_id,
                "generation": 1,
                "change_status": const.MemberChangeStati.committed,
                "persona_id": new_id,
                "change_note": "Persona creation.",
            })
            ## remove unlogged attributes
            del data['password_hash']
            del data['fulltext']
            self.sql_insert(rs, "core.changelog", data)
            dn = "uid={},{}".format(new_id, self.conf.LDAP_UNIT_NAME)
            self.core_log(rs, const.CoreLogCodes.persona_creation, new_id)
            with self.ldap_connect() as l:
                l.add(dn, object_class='cdePersona', attributes=attributes)
        return new_id

    @access("anonymous")
    def login(self, rs, username, password, ip):
        """Create a new session. This invalidates all existing sessions for this
        persona. Sessions are bound to an IP-address, for bookkeeping purposes.

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
        ## note the lower-casing for email addresses
        query = glue("SELECT id, password_hash FROM core.personas",
                     "WHERE username = lower(%s) AND is_active = True")
        data = self.query_one(rs, query, (username,))
        verified = bool(data) and self.conf.CDEDB_OFFLINE_DEPLOYMENT
        if not verified and data:
            verified = self.verify_password(password, data["password_hash"])
        if not verified:
            ## log message to be picked up by fail2ban
            self.logger.warning("CdEDB login failure from {} for {}".format(
                ip, username))
            return None
        else:
            sessionkey = str(uuid.uuid4())
            with Atomizer(rs):
                query = glue(
                    "UPDATE core.sessions SET is_active = False",
                    "WHERE persona_id = %s AND is_active = True")
                self.query_exec(rs, query, (data["id"],))
                query = glue(
                    "INSERT INTO core.sessions (persona_id, ip, sessionkey)",
                    "VALUES (%s, %s, %s)")
                self.query_exec(rs, query, (data["id"], ip, sessionkey))
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
        ids = affirm_array("id", ids)
        if ids == (rs.user.persona_id,):
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
        ids = affirm_array("id", ids)
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
        ids = affirm_array("id", ids)
        required_roles = required_roles or tuple()
        required_roles = set(affirm_array("str", required_roles))
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
        return bool(data['num'])

    def _generate_reset_cookie(self, rs, persona_id, salt, verify=False):
        """Create a cookie which authorizes a specific reset action.

        The cookie depends on the inputs as well as a server side secret.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type salt: str
        :type verify: bool
        :param verify: Signal, that we are invoked by
          :py:meth:`_verify_reset_cookie`, which means, that we have to skip
          some checks.
        :rtype: str
        """
        with Atomizer(rs):
            if not verify and not self.is_admin(rs):
                roles = unwrap(self.get_roles_multi(rs, (persona_id,)))
                if any("admin" in role for role in roles):
                    raise PrivilegeError("Preventing reset of admin.")
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            plain = "{}-{}-{}".format(password_hash, persona_id, salt)
            h = hashlib.sha512()
            h.update(plain.encode("ascii"))
            return h.hexdigest()

    def _verify_reset_cookie(self, rs, persona_id, salt, cookie):
        """Check a provided cookie for correctness.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type cookie: str
        :type salt: str
        :rtype: bool
        """
        correct = self._generate_reset_cookie(rs, persona_id, salt, verify=True)
        return correct == cookie

    def modify_password(self, rs, persona_id, new_password, old_password=None,
                        reset_cookie=None):
        """Helper for manipulationg password entries.

        If ``new_password`` is ``None``, a new password is generated
        automatically. An authorization must be provided, either by
        ``old_password``, ``reset_cookie`` or being an admin.

        This escalates database connection privileges in the case of a
        password reset (which is in its nature by anonymous).

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type new_password: str or None
        :type old_password: str or None
        :type reset_cookie: str or None
        :returns: The ``bool`` indicates success and the ``str`` is
          either the new password or an error message.
        :rtype: (bool, str)
        """
        if not old_password and not reset_cookie:
            return False, "No authorization provided."
        if old_password:
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            if not self.verify_password(old_password, password_hash):
                return False, "Password verification failed."
        if reset_cookie:
            if not self.verify_reset_cookie(rs, persona_id, reset_cookie):
                return False, "Reset verification failed."
        if new_password and (not self.is_admin(rs)
                             or persona_id == rs.user.persona_id):
            if not validate.is_password_strength(new_password):
                return False, "Password too weak."
        ## escalate db privilige role in case of resetting passwords
        orig_conn = None
        if reset_cookie and not "persona" in rs.user.roles:
            if rs.conn.is_contaminated:
                raise RuntimeError("Atomized -- impossible to escalate.")
            orig_conn = rs.conn
            rs.conn = self.connpool['cdb_persona']
        if not new_password:
            new_password = ''.join(random.choice(
                'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789' +
                '!@#$%&*()[]-=<>') for _ in range(12))
        ## do not use set_persona_data since it doesn't operate on password
        ## hashes by design
        query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
        with tempfile.NamedTemporaryFile(mode='w') as f:
            f.write(new_password)
            f.flush()
            ldap_passwd = subprocess.check_output(
                ['/usr/sbin/slappasswd', '-T', f.name, '-h', '{SSHA}', '-n'])
        dn = "uid={},{}".format(persona_id, self.conf.LDAP_UNIT_NAME)
        with rs.conn as conn:
            with conn.cursor() as cur:
                self.execute_db_query(
                    cur, query,
                    (self.encrypt_password(new_password), persona_id))
                ret = cur.rowcount
                with self.ldap_connect() as l:
                    l.modify(dn, {'userPassword': [(ldap3.MODIFY_REPLACE,
                                                    [ldap_passwd])]})
        if orig_conn:
            ## deescalate
            rs.conn = orig_conn
        return ret, new_password

    @access("persona")
    def change_password(self, rs, persona_id, old_password, new_password):
        """
        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type old_password: str
        :type new_password: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        persona_id = affirm("id", persona_id)
        old_password = affirm("str", old_password)
        new_password = affirm("str", new_password)
        if rs.user.persona_id == persona_id or self.is_admin(rs):
            ret = self.modify_password(rs, persona_id, new_password,
                                       old_password=old_password)
            self.core_log(rs, const.CoreLogCodes.password_change, persona_id)
            return ret
        else:
            raise PrivilegeError("Not privileged.")

    @access("anonymous")
    def make_reset_cookie(self, rs, email):
        """Perform preparation for a recovery.

        This generates a reset cookie which can be used in a second step
        to actually reset the password. To reset the password for a
        privileged account you need to have privileges yourself.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        email = affirm("email", email)
        data = self.sql_select_one(
            rs, "core.personas", ("id",), email,
            entity_key="username")
        if not data:
            return False, "Nonexistant user."
        persona_id = unwrap(data)
        if not self.is_admin(rs):
            roles = unwrap(self.get_roles_multi(rs, (persona_id,)))
            if any("admin" in role for role in roles):
                ## do not allow password reset by anonymous for privileged
                ## users, otherwise we incur a security degradation on the
                ## RPC-interface
                return False, "Privileged user."
        ret = self.generate_reset_cookie(rs, persona_id)
        self.core_log(rs, const.CoreLogCodes.password_reset_cookie, persona_id)
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
        data = self.sql_select_one(
            rs, "core.personas", ("id",), email,
            entity_key="username")
        if not data:
            return False, "Nonexistant user."
        persona_id = unwrap(data)
        ret = self.modify_password(rs, persona_id, new_password,
                                   reset_cookie=cookie)
        self.core_log(rs, const.CoreLogCodes.password_reset, persona_id)
        return ret

    @access("core_admin")
    def new_password(self, rs, email, cookie):
        """Generate a new password

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :type cookie: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        email = affirm("email", email)
        cookie = affirm("str", cookie)
        data = self.sql_select_one(
            rs, "core.personas", ("id",), email,
            entity_key="username")
        if not data:
            return False, "Nonexistant user."
        persona_id = unwrap(data)
        ret = self.modify_password(rs, persona_id, new_password=None,
                                   reset_cookie=cookie)
        self.core_log(rs, const.CoreLogCodes.password_generated, persona_id)
        return ret

    @access("anonymous")
    def genesis_request(self, rs, data):
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new request or None if the username is already taken
        """
        data = affirm("genesis_case", data, creation=True)
        if self.verify_existence(rs, data['username']):
            return None
        data['case_status'] = const.GenesisStati.unconfirmed
        ret = self.sql_insert(rs, "core.genesis_cases", data)
        self.core_log(rs, const.CoreLogCodes.genesis_request, persona_id=None,
                      additional_info=data['username'])
        return ret

    @access("anonymous")
    def genesis_verify(self, rs, case_id):
        """Confirm the new email address and proceed to the next stage.

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
    def genesis_list_cases(self, rs, realm=None, stati=None):
        """List persona creation cases.

        Restrict to certain stati and certain target realms.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type stati: {int}
        :param stati: restrict to these stati
        :type stati: str or None
        :param stati: restrict to this realm
        :rtype: {int: {str: object}}
        :returns: dict mapping case ids to dicts containing information
          about the case
        """
        realm = affirm("str_or_None", realm)
        stati = stati or set()
        stati = affirm_array("enum_genesisstati", stati)
        if "{}_admin".format(realm or "core") not in rs.user.roles:
            raise PrivilegeError("Not privileged.")
        query = glue("SELECT id, ctime, username, given_names, family_name,",
                     "case_status FROM core.genesis_cases")
        connector = " WHERE"
        params = []
        if realm:
            query = glue(query, connector, "realm = %s")
            params.append(realm)
            connector = "AND"
        if stati:
            query = glue(query, connector, "case_status = ANY(%s)")
            params.append(stati)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access("anonymous")
    def genesis_my_case(self, rs, case_id, secret):
        """Retrieve one dataset.

        This is seperately to allow secure anonymous access.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :type secret: str
        :rtype: {int: {str: object}}
        :returns: the requested data or None if wrong secret
        """
        case_id = affirm("id", case_id)
        secret = affirm("str", secret)
        data = self.sql_select_one(rs, "core.genesis_cases",
                                   GENESIS_CASE_FIELDS, case_id)
        if secret != data['secret']:
            return None
        return data

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
        ids = affirm_array("id", ids)
        data = self.sql_select(rs, "core.genesis_cases", GENESIS_CASE_FIELDS,
                               ids)
        if ("core_admin" not in rs.user.roles
                and any("{}_admin".format(e['realm']) not in rs.user.roles
                        for e in data)):
            raise PrivilegeError("Not privileged.")
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
                raise PrivilegeError("Not privileged.")
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

    @access("anonymous")
    def genesis_check(self, rs, case_id, secret, realm):
        """Verify input data for genesis case.

        This is a security check, which enables us to share a
        non-ephemeral private link after a moderator approved a request.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :type secret: str
        :type realm: str
        :rtype: bool
        """
        case_id = affirm("id", case_id)
        secret = affirm("str", secret)
        realm = affirm("str", realm)
        case = self.sql_select_one(rs, "core.genesis_cases",
                                   ("case_status", "secret", "realm"), case_id)
        return (bool(case)
                and case['case_status'] == const.GenesisStati.approved
                and case['secret'] == secret
                and case['realm'] == realm)

    @access("anonymous")
    def genesis(self, rs, case_id, secret, realm, data):
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account. This heavily escalates privileges to allow the creation
        of a user with an anonymous role.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type case_id: int
        :type realm: str
        :type secret: str
        :param secret: Verification for the authenticity of the invocation.
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        case_id = affirm("id", case_id)
        secret = affirm("str", secret)
        realm = affirm("str", realm)
        ACCESS_BITS = {
            'cde' : {
                'is_cde_realm': True,
                'is_event_realm': True,
                'is_assembly_realm': True,
                'is_ml_realm': True,
                ## Do not specify membership
                ## 'is_member': True,
                'is_searchable': False,
            },
            'event' : {
                'is_cde_realm': False,
                'is_event_realm': True,
                'is_assembly_realm': False,
                'is_ml_realm': True,
                'is_member': False,
                'is_searchable': False,
            },
            'assembly' : {
                'is_cde_realm': False,
                'is_event_realm': False,
                'is_assembly_realm': True,
                'is_ml_realm': True,
                'is_member': False,
                'is_searchable': False,
            },
            'ml' : {
                'is_cde_realm': False,
                'is_event_realm': False,
                'is_assembly_realm': False,
                'is_ml_realm': True,
                'is_member': False,
                'is_searchable': False,
            },
        }
        ## Fix realms, so that the persona validator does the correct thing
        data.update(ACCESS_BITS[realm])
        data = affirm("persona", data, creation=True)

        ## escalate priviliges
        if rs.conn.is_contaminated:
            raise RuntimeError("Atomized -- impossible to escalate.")
        orig_conn = rs.conn
        rs.conn = self.connpool['cdb_admin']
        orig_roles = rs.user.roles
        rs.user.roles = rs.user.roles | {"persona", "core_admin", realm,
                                         "{}_admin".format(realm)}

        with Atomizer(rs):
            case = self.sql_select_one(rs, "core.genesis_cases",
                                       GENESIS_CASE_FIELDS, case_id)
            if not case or case['secret'] != secret:
                return None, "Invalid case."
            if case['case_status'] != const.GenesisStati.approved:
                return None, "Invalid state."
            tier = privilege_tier(extract_roles(data))
            if "{}_admin".format(case['realm']) not in tier:
                return None, "Wrong target realm."
            data['username'] = case['username']
            data['given_names'] = case['given_names']
            data['family_name'] = case['family_name']
            ret = self.create_persona(
                rs, data, submitted_by=case['reviewer'])
            update = {
                'id': case_id,
                'case_status': const.GenesisStati.finished,
            }
            self.sql_update(rs, "core.genesis_cases", update)

        ## deescalate privileges
        rs.conn = orig_conn
        rs.user.roles = orig_roles
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
             (persona['family_name'],persona['given_names'],)),
            (21, "username = %s", (persona['username'],)),)
        ## Omit queries where some parameters are None
        queries = tuple(e for e in queries if all(x is not None for x in e[2]))
        for score, condition, params in queries:
            query = "SELECT id FROM core.personas WHERE {}".format(condition)
            result = self.query_all(rs, query, params)
            for e in result:
                scores[unwrap(e)] += score
        CUTOFF = 21
        persona_ids = tuple(k for k, v in scores.items() if v > CUTOFF)
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
        data = affirm("meta_info", data, keys=self.conf.META_INFO_KEYS)
        with Atomizer(rs):
            query = "SELECT info FROM core.meta_info LIMIT 1"
            the_data = unwrap(self.query_one(rs, query, tuple()))
            the_data.update(data)
            query = "UPDATE core.meta_info SET info = %s"
            return self.query_exec(rs, query, (psycopg2.extras.Json(the_data),))

    @access("core_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

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
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query)
