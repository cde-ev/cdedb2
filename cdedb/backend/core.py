#!/usr/bin/env python3

"""The core backend provides services which are common for all
users/personas independent of their realm. Thus we have no user role
since the basic division is between known accounts and anonymous
accesses.
"""
from cdedb.backend.common import AbstractBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon, singularize,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    create_fulltext)
from cdedb.common import (
    glue, PERSONA_DATA_FIELDS, extract_realm, MEMBER_DATA_FIELDS,
    GENESIS_CASE_FIELDS, PrivilegeError, unwrap)
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import Atomizer
import cdedb.validation as validate
import cdedb.database.constants as const

from passlib.hash import sha512_crypt
import copy
import uuid
import argparse
import random
import ldap
import tempfile
import subprocess

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

class LDAPConnection:
    """Wrapper around :py:class:`ldap.LDAPObject`.

    This acts as context manager ensuring that the connection to the
    LDAP server is correctly terminated.
    """
    def __init__(self, url, user, password):
        """
        :param url: URL of LDAP server
        :type url: str
        :type user: str
        :type password: str
        """
        self._ldap_con = ldap.initialize(url)
        self._ldap_con.simple_bind_s(user, password)

    def modify_s(self, dn, modlist):
        self._ldap_con.modify_s(dn, modlist)

    def add_s(self, dn, modlist):
        self._ldap_con.add_s(dn, modlist)

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, tb):
        self._ldap_con.unbind()
        return None

class CoreBackend(AbstractBackend):
    """Access to this is probably necessary from everywhere, so we need
    ``@internal_access`` quite often. """
    realm = "core"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        secrets = SecretsConfig(configpath)
        self.ldap_connect = lambda: LDAPConnection(
            self.conf.LDAP_URL, self.conf.LDAP_USER, secrets.LDAP_PASSWORD)

    def establish(self, sessionkey, method, allow_internal=False):
        return super().establish(sessionkey, method,
                                 allow_internal=allow_internal)

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

    def core_log(self, rs, code, persona_id, additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type code: int
        :param code: One of :py:class:`cdedb.database.constants.CoreLogCodes`.
        :type persona_id: int or None
        :param persona_id: ID of affected user
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
         """
        ## do not use sql_insert since it throws an error for selecting the id
        query = glue(
            "INSERT INTO core.log",
            "(code, submitted_by, persona_id, additional_info)",
            "VALUES (%s, %s, %s, %s)")
        return self.query_exec(
            rs, query, (code, rs.user.persona_id, persona_id, additional_info))

    @access("core_admin")
    def retrieve_log(self, rs, codes=None, persona_id=None, start=None,
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
            rs, "enum_corelogcodes", "persona", "core.log", codes, persona_id,
            start, stop)

    ##
    ## changelog functionality
    ## =======================
    ##
    ## In a perfect world this would reside in the cde realm, however the
    ## core backend has to be aware of the changelog to perform updates on
    ## dataset of cde users. The trivial attempt to solve this by delegation
    ## to the cde backend results in circular dependencies -- bad. Thus this
    ## location.
    ##
    ## The functionality here should only be used directly if strictly
    ## necessary. For general purpose it is publically exported by the cde
    ## backend. As a consequence of this, the code assumes that it needn't
    ## do validation here.
    ##

    @internal_access("persona")
    def changelog_is_logged(self, rs, anid):
        """Helper to determine wheter the changelog is responsible for a
        given persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type anid: int
        :rtype: bool
        """
        query = glue("SELECT COUNT(*) AS num FROM core.changelog",
                     "WHERE persona_id = %s")
        return unwrap(self.query_one(rs, query, (anid,))) > 0

    @internal_access("formermember")
    def changelog_submit_change(
            self, rs, data, generation, allow_username_change=False,
            may_wait=True, change_note=''):
        """This implements the changelog and updates the fulltext in
        addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.set_user_data`
        does. If a change requires review it has to be committed using
        :py:meth:`changelog_resolve_change` by an administrator.

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

            ## get current state and check for archived members
            history = self.changelog_get_history(
                rs, data['id'], generations=(current_generation,))
            current_data = history[current_generation]
            if (current_data['status'] == const.PersonaStati.archived_member
                    and data.get('status') not in const.CDE_STATI):
                raise RuntimeError("Editing archived member impossible.")

            ## stash pending change if we may not wait
            diff = None
            if (current_data['change_status']
                    == const.MemberChangeStati.pending and not may_wait):
                old_data = unwrap(self.cde_retrieve_user_data(
                    rs, (data['id'],)))
                diff = {key: current_data[key] for key in old_data
                        if old_data[key] != current_data[key]}
                current_data = old_data
                query = glue("UPDATE core.changelog SET change_status = %s",
                             "WHERE persona_id = %s AND change_status = %s")
                self.query_exec(rs, query, (
                    const.MemberChangeStati.displaced, data['id'],
                    const.MemberChangeStati.pending))

            ## determine if something changed
            changed_fields = {key for key, value in data.items()
                              if value != current_data[key]}
            if not changed_fields:
                if diff:
                    ## reenable old change if we were going to displace it
                    query = glue("UPDATE core.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND generation = %s")
                    self.query_exec(rs, query, (const.MemberChangeStati.pending,
                                                data['id'], current_generation))
                return 0

            ## Determine if something requiring a review changed.
            ##
            ## This is a bit delicate, since the core backend doesn't handle
            ## changes which require review. The cde backend has to do the
            ## right thing, so that this works (i.e. not calling
            ## :py:meth:`set_persona_data` directly).
            fields_requiring_review = {'birthday', 'family_name', 'given_names'}
            requires_review = (changed_fields & fields_requiring_review
                               and not self.is_admin(rs))

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
            self.sql_insert(rs, "core.changelog", insert)

            ## resolve change if it doesn't require review
            if not requires_review:
                ret = self.changelog_resolve_change(
                    rs, data['id'], next_generation, ack=True, reviewed=False,
                    allow_username_change=allow_username_change)
            else:
                ret = -1
            if not may_wait and ret <= 0:
                raise RuntimeError("Non-waiting change not committed.")

            ## pop the stashed change
            if diff:
                if set(diff) & changed_fields:
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

    @internal_access("cde_admin")
    def changelog_resolve_change(self, rs, persona_id, generation, ack,
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
            old_data = unwrap(self.cde_retrieve_user_data(rs, (persona_id,)))
            relevant_keys = tuple(key for key in old_data
                                  if data[key] != old_data[key])
            relevant_keys += ('id',)
            if not allow_username_change and 'username' in relevant_keys:
                raise RuntimeError("Modification of username prevented.")
            pkeys = tuple(key for key in relevant_keys if key in
                          PERSONA_DATA_FIELDS)
            ukeys = tuple(key for key in relevant_keys if key in
                          MEMBER_DATA_FIELDS)

            ## commit changes
            ret = 0
            if len(pkeys) > 1:
                pdata = {key: data[key] for key in pkeys}
                ret = self.set_persona_data(
                    rs, pdata, allow_username_change=allow_username_change,
                    change_logged=True)
                if not ret:
                    raise RuntimeError("Modification failed.")
            if len(ukeys) > 0:
                query = glue("UPDATE cde.member_data SET ({}) = ({})",
                             "WHERE persona_id = %s")
                query = query.format(", ".join(ukeys),
                                     ", ".join(("%s",) * len(ukeys)))
                params = tuple(data[key] for key in ukeys) + (data['id'],)
                ret = self.query_exec(rs, query, params)
                if not ret:
                    raise RuntimeError("Modification failed.")
        if ret > 0:
            with Atomizer(rs):
                new_data = unwrap(self.cde_retrieve_user_data(rs,
                                                              (data['id'],)))
                text = create_fulltext(new_data)
                query = glue("UPDATE cde.member_data SET fulltext = %s",
                             "WHERE persona_id = %s")
                self.query_exec(rs, query, (text, data['id']))
        return ret

    @internal_access("formermember")
    def changelog_get_generations(self, rs, ids):
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {e['persona_id']: e['generation'] for e in data}

    @internal_access("cde_admin")
    def changelog_get_changes(self, rs, stati):
        """Retrive changes in the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type stati: [int]
        :param stati: limit changes to those with a status in this
        :rtype: {int: {str: object}}
        :returns: dict mapping persona ids to dicts containing information
          about the change and the persona
        """
        query = glue("SELECT persona_id, given_names, family_name, generation",
                     "FROM core.changelog WHERE change_status = ANY(%s)")
        data = self.query_all(rs, query, (stati,))
        return {e['persona_id']: e for e in data}

    @internal_access("cde_admin")
    def changelog_get_history(self, rs, anid, generations):
        """Retrieve history of a member data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type anid: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int: {str: object}}
        :returns: mapping generation to data set
        """
        fields = list(PERSONA_DATA_FIELDS)
        fields.remove("id")
        fields.append("persona_id AS id")
        fields.extend(MEMBER_DATA_FIELDS)
        fields.extend(("submitted_by", "reviewed_by", "ctime", "generation",
                       "change_status"))
        query = "SELECT {} FROM core.changelog WHERE persona_id = %s".format(
            ", ".join(fields))
        params = [anid]
        if generations is not None:
            query = glue(query, "AND generation = ANY(%s)")
            params.append(generations)
        data = self.query_all(rs, query, params)
        return {e['generation']: e for e in data}

    def cde_retrieve_user_data(self, rs, ids):
        """This is a hack.

        Since we moved some functionality from the cde backend to the core
        backend we have to inline this copy of
        :py:meth:`cdedb.backend.cde.retrieve_user_data`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        query = glue(
            "SELECT {} FROM cde.member_data AS u JOIN core.personas AS p",
            "ON u.persona_id = p.id WHERE p.id = ANY(%s)")
        query = query.format(", ".join(PERSONA_DATA_FIELDS +
                                       MEMBER_DATA_FIELDS))
        data = self.query_all(rs, query, (ids,))
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {d['id']: d for d in data}

    ##
    ## end of changelog functionality
    ##

    @internal_access("persona")
    @singularize("retrieve_persona_data_one")
    def retrieve_persona_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        data = self.sql_select(rs, "core.personas", PERSONA_DATA_FIELDS, ids)
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {d['id']: d for d in data}

    @internal_access("persona")
    def set_persona_data(self, rs, data, allow_username_change=False,
                         change_note=None, change_logged=False):
        """Update only some keys of a data set. If ``keys`` is not passed
        all keys available in ``data`` are updated.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :type allow_username_change: bool
        :param allow_username_change: Usernames are special because they
          are used for login and password recovery, hence we require an
          explicit statement of intent to change a username. Obviously this
          should only be set if necessary.
        :type change_note: str
        :param change_note: Comment to record in the changelog entry. This
          is ignored if the persona is not in the changelog.
        :type change_logged: bool
        :param change_logged: True if the change is known to the changelog,
          if not we have to delegate to the changelog which will call this
          method again with ``change_logged`` set to True.
        :rtype: int
        :returns: default return code
        """
        keys = tuple(key for key in data if (key in PERSONA_DATA_FIELDS
                                             and key != "id"))
        if not keys:
            ## this is a bit of a nitpick, but we choose to say, that an
            ## empty change applies successfully
            return 1
        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        privileged_fields = {'is_active', 'status', 'db_privileges',
                             'cloud_account'}
        if not self.is_admin(rs) and (set(keys) & privileged_fields):
            ## be naughty and take a peak
            if (set(keys) == {'status'} and data['id'] == rs.user.persona_id
                    and data['status'] == const.PersonaStati.searchmember
                    and rs.user.is_member):
                ## allow upgrading self to searchable member
                pass
            else:
                raise PrivilegeError("Modifying sensitive key forbidden.")
        if 'username' in data and not allow_username_change:
            raise RuntimeError("Modification of username prevented.")
        if change_note is None:
            change_note = "Unspecified change."

        ## reroute through the changelog if necessary
        if not change_logged and self.changelog_is_logged(rs, data['id']):
            ## do not allow the change to wait, since the core backend
            ## doesn't handle pending changes
            return self.changelog_submit_change(
                rs, data, generation=None,
                allow_username_change=allow_username_change,
                may_wait=False, change_note=change_note)

        ## prevent modification of archived members
        query = "SELECT status FROM core.personas WHERE id = %s"
        current_data = self.query_one(rs, query, (data['id'],))
        if (current_data['status'] == const.PersonaStati.archived_member
                and data.get('status') not in const.CDE_STATI):
            raise RuntimeError("Editing archived member impossible.")

        query = "UPDATE core.personas SET ({}) = ({}) WHERE id = %s".format(
            ", ".join(keys), ", ".join(("%s",) * len(keys)))
        ldap_ops = []
        if 'username' in data:
            ldap_ops.append((ldap.MOD_REPLACE, 'sn', "({})".format(
                data['username'])))
            ldap_ops.append((ldap.MOD_REPLACE, 'mail', data['username']))
        if 'display_name' in data:
            ldap_ops.append((ldap.MOD_REPLACE, 'cn', data['display_name']))
            ldap_ops.append((ldap.MOD_REPLACE, 'displayName',
                             data['display_name']))
        if 'cloud_account' in data:
            ldap_ops.append((ldap.MOD_REPLACE, 'cloudAccount',
                             ldap_bool(data['cloud_account'])))
        if 'is_active' in data:
            ldap_ops.append((ldap.MOD_REPLACE, 'isActive',
                             ldap_bool(data['is_active'])))
        dn = "uid={},{}".format(data['id'], self.conf.LDAP_UNIT_NAME)
        ## Atomize so that ldap and postgres do not diverge.
        with Atomizer(rs):
            num = self.query_exec(rs, query, tuple(
                data[key] for key in keys) + (data['id'],))
            if not num:
                raise ValueError("Nonexistant user.")
            self.core_log(rs, const.CoreLogCodes.persona_change, data['id'])
            if ldap_ops:
                with self.ldap_connect() as l:
                    l.modify_s(dn, ldap_ops)
        return num

    @access("persona")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        """Aquire data sets for specified ids.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str: object}]
        """
        ids = affirm_array("int", ids)
        return self.retrieve_persona_data(rs, ids)

    @access("anonymous")
    def login(self, rs, username, password, ip):
        """Create a new session. This invalidates all existing sessions for this
        persona. Sessions are bound to an IP-address, for bookkeeping purposes.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        if (not data or
                not self.verify_password(password, data["password_hash"])):
            ## log message to be picked up by fail2ban
            self.logger.warning("CdEDB login failure from {} for {}".format(
                ip, username))
            return None
        else:
            sessionkey = str(uuid.uuid4())
            query = glue(
                "UPDATE core.sessions SET is_active = False",
                "WHERE (persona_id = %s OR ip = %s) AND is_active = True;\n",
                ## next
                "INSERT INTO core.sessions (persona_id, ip, sessionkey)",
                "VALUES (%s, %s, %s)")
            self.query_exec(rs, query,
                            (data["id"], ip, data["id"], ip, sessionkey))
            return sessionkey

    @access("persona")
    def logout(self, rs):
        """Invalidate the current session.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: bool
        """
        ids = affirm_array("int", ids)
        if ids == (rs.user.persona_id,):
            return True
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE id = ANY(%s)"
        data = self.query_one(rs, query, (ids,))
        return data['num'] == len(ids)

    @access("persona")
    @singularize("get_realm")
    def get_realms(self, rs, ids):
        """Resolve ids into realms.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: str}
        :returns: dict mapping id to realm
        """
        ids = affirm_array("int", ids)
        if ids == (rs.user.persona_id,):
            return {rs.user.persona_id: rs.user.realm}
        data = self.sql_select(rs, "core.personas", ("id", "status"), ids)
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {d['id']: extract_realm(d['status']) for d in data}

    @access("persona")
    def verify_personas(self, rs, ids, stati=None):
        """Check wether certain ids map to actual personas.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :type stati: [int] or None
        :param stati: If provided restrict matches to these PersonaStati.
        :rtype: [int]
        :returns: All ids which successfully validated.
        """
        ids = affirm_array("int", ids)
        stati = affirm_array("int", stati, allow_None=True)
        query = "SELECT id FROM core.personas WHERE id = ANY(%s)"
        params = (ids,)
        if stati:
            query = glue(query, "AND status = ANY(%s)")
            params += (stati,)
        data = self.query_all(rs, query, params)
        return tuple(e['id'] for e in data)

    @access("anonymous")
    def verify_existence(self, rs, email):
        """Check wether a certain email belongs to any persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type email: str
        :rtype: bool
        """
        email = affirm("email", email)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE username = %s"
        data = self.query_one(rs, query, (email,))
        return bool(data['num'])

    def modify_password(self, rs, persona_id, old_password, new_password):
        """Helper for manipulationg password entries. If ``new_password`` is
        ``None``, a new password is generated automatically; in this case
        ``old_password`` may also be ``None`` (this is a password reset).

        This escalates database connection privileges in the case of a
        password reset (which is in its nature by anonymous).

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type old_password: str or None
        :type new_password: str or None
        :type data: {str: object}
        :rtype: (bool, str)
        :returns: The ``bool`` indicates success and the ``str`` is
          either the new password or an error message.
        """
        password_hash = unwrap(self.sql_select_one(
            rs, "core.personas", ("password_hash",), persona_id))
        if new_password is not None and (not self.is_admin(rs)
                                         or persona_id == rs.user.persona_id):
            if not validate.is_password_strength(new_password):
                return False, "Password too weak."
            if not self.verify_password(old_password, password_hash):
                return False, "Password verification failed."
        ## escalate db privilige role in case of resetting passwords
        orig_conn = None
        if not rs.user.is_persona and new_password is None:
            if rs.conn.is_contaminated:
                raise RuntimeError("Atomized -- impossible to escalate.")
            orig_conn = rs.conn
            rs.conn = self.connpool['cdb_persona']
        if new_password is None:
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
                    l.modify_s(dn, ((ldap.MOD_REPLACE, 'userPassword',
                                     ldap_passwd),))
        if orig_conn:
            ## deescalate
            rs.conn = orig_conn
        return ret, new_password

    @access("persona")
    def change_password(self, rs, persona_id, old_password, new_password):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type old_password: str
        :type new_password: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        persona_id = affirm("int", persona_id)
        old_password = affirm("str_or_None", old_password)
        new_password = affirm("str_or_None", new_password)
        if rs.user.persona_id == persona_id or self.is_admin(rs):
            ret = self.modify_password(rs, persona_id, old_password,
                                       new_password)
            self.core_log(rs, const.CoreLogCodes.password_change, persona_id)
            return ret
        else:
            raise PrivilegeError("Not privileged.")

    @access("anonymous")
    def reset_password(self, rs, email):
        """Perform a recovery, generating a new password (which will be sent
        to the email address). To reset the password for a privileged
        account you need to have privileges yourself.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type email: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        email = affirm("email", email)
        data = self.sql_select_one(
            rs, "core.personas", ("id", "db_privileges"), email,
            entity_key="username")
        if not data:
            return False, "Nonexistant user."
        if data['db_privileges'] > 0 and not self.is_admin(rs):
            ## do not allow password reset by anonymous for privileged
            ## users, otherwise we incur a security degradation on the
            ## RPC-interface
            return False, "Privileged user."
        ret = self.modify_password(rs, data['id'], None, None)
        self.core_log(rs, const.CoreLogCodes.password_reset, persona_id=None,
                      additional_info=email)
        return ret

    @access("persona")
    def change_username(self, rs, persona_id, new_username, password):
        """Since usernames are used for login, this needs a bit of care.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type new_username: str
        :type password: str or None
        :rtype: (bool, str)
        """
        persona_id = affirm("int", persona_id)
        new_username = affirm("email", new_username)
        password = affirm("str_or_None", password)
        with Atomizer(rs):
            if self.verify_existence(rs, new_username):
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
                if self.set_persona_data(
                        rs, new_data, allow_username_change=True,
                        change_note=change_note):
                    return True, new_username
        return False, "Failed."

    @access("core_admin")
    def adjust_persona(self, rs, data, change_note=None):
        """Change a persona.

        This is for administrative purposes (like toggling account
        activity). Normally one should use the change_user functions of
        the respective realm to change a persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :type change_note: str
        :rtype: int
        :returns: default return code
        """
        data = affirm("persona_data", data)
        if "username" in data:
            raise RuntimeError("Use change_username().")
        change_note = affirm("str_or_None", change_note)
        if change_note is None:
            change_note = "Unspecified change."
        return self.set_persona_data(rs, data, change_note=change_note)

    @internal_access("core_admin")
    def create_persona(self, rs, data):
        """Make a new persona.

        This is to be called by a create_user function, which creates a
        real user and not just a persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        ## filter relevant parts of the dict
        data = {k: v for k, v in data.items() if k in PERSONA_DATA_FIELDS}
        data['db_privileges'] = 0 ## everybody starts with no privileges
        ## modified version of hash for 'secret' and thus safe/unknown plaintext
        data['password_hash'] = glue(
            "$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/",
            "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHE/si/")
        assert(set(data.keys())
               == (set(PERSONA_DATA_FIELDS) | {'password_hash'}) - {"id"})
        ldap_ops = (
            ('objectClass', 'cdePersona'),
            ('sn', "({})".format(data['username'])),
            ('mail', data['username']),
            ## againg slight modification of 'secret'
            ('userPassword', "{SSHA}D5JG6KwFxs11jv0LnEmFSeBCjGrHCDWV"),
            ('cn', data['display_name']),
            ('displayName', data['display_name']),
            ('cloudAccount', ldap_bool(data['cloud_account'])),
            ('isActive', ldap_bool(data['is_active'])))
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "core.personas", data)
            dn = "uid={},{}".format(new_id, self.conf.LDAP_UNIT_NAME)
            self.core_log(rs, const.CoreLogCodes.persona_creation, new_id)
            with self.ldap_connect() as l:
                l.add_s(dn, ldap_ops)
        return new_id

    @access("anonymous")
    def genesis_request(self, rs, data):
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new request or 0 if the username is already taken
        """
        data = affirm("genesis_case_data", data, creation=True)
        if self.verify_existence(rs, data['username']):
            return 0
        data['case_status'] = const.GenesisStati.unconfirmed
        ret = self.sql_insert(rs, "core.genesis_cases", data)
        self.core_log(rs, const.CoreLogCodes.genesis_request, persona_id=None,
                      additional_info=data['username'])
        return ret

    @access("anonymous")
    def genesis_verify(self, rs, case_id):
        """Confirm the new email address and proceed to the next stage.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type case_id: int
        :rtype: int
        :returns: default return code
        """
        case_id = affirm("int", case_id)
        query = glue("UPDATE core.genesis_cases SET case_status = %s",
                     "WHERE id = %s AND case_status = %s")
        params = (const.GenesisStati.to_review, case_id,
                  const.GenesisStati.unconfirmed)
        return self.query_exec(rs, query, params)

    @access("core_admin")
    def genesis_list_cases(self, rs, stati):
        """List persona creation cases with certain stati.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type stati: {int}
        :param stati: restrict to these stati
        :rtype: {int: {str: object}}
        :returns: dict mapping case ids to dicts containing information
          about the case
        """
        stati = affirm_array("int", stati)
        fields = ("id", "ctime", "username", "given_names", "family_name",
                  "case_status")
        data = self.sql_select(rs, "core.genesis_cases", fields, stati,
                               entity_key="case_status")
        return {e['id']: e for e in data}

    @access("anonymous")
    def genesis_my_case(self, rs, case_id, secret):
        """Retrieve one dataset.

        This is seperately to allow secure anonymous access.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type case_id: int
        :type secret: str
        :rtype: {int: {str: object}}
        :returns: the requested data or None if wrong secret
        """
        case_id = affirm("int", case_id)
        secret = affirm("str", secret)
        data = self.sql_select_one(rs, "core.genesis_cases",
                                   GENESIS_CASE_FIELDS, case_id)
        if secret != data['secret']:
            return None
        return data

    @access("core_admin")
    @singularize("genesis_get_case")
    def genesis_get_cases(self, rs, ids):
        """Retrieve datasets for persona creation cases.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to the requested data
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "core.genesis_cases", GENESIS_CASE_FIELDS,
                               ids)
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {e['id']: e for e in data}

    @access("core_admin")
    def genesis_modify_case(self, rs, data):
        """Modify a persona creation case.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("genesis_case_data", data)
        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "core.genesis_cases", ("case_status", "username"),
                data['id'])
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for core services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    core_backend = CoreBackend(args.configpath)
    conf = Config(args.configpath)
    core_server = make_RPCDaemon(core_backend, conf.CORE_SOCKET,
                                 access_log=conf.CORE_ACCESS_LOG)
    if not conf.CDEDB_DEV and conf.CORE_ACCESS_LOG:
        raise RuntimeError("Logging will disclose passwords.")
    run_RPCDaemon(core_server, conf.CORE_STATE_FILE)
