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
from pathlib import Path
from secrets import token_hex
from typing import (
    Any, Collection, Dict, List, Optional, Set, Tuple, Union, cast, overload,
)

from passlib.hash import sha512_crypt
from typing_extensions import Protocol

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    AbstractBackend, access, affirm_set_validation as affirm_set,
    affirm_validation_typed as affirm,
    affirm_validation_typed_optional as affirm_optional, internal, singularize,
)
from cdedb.common import (
    ADMIN_KEYS, GENESIS_CASE_FIELDS, GENESIS_REALM_OVERRIDE, PERSONA_ALL_FIELDS,
    PERSONA_ASSEMBLY_FIELDS, PERSONA_CDE_FIELDS, PERSONA_CORE_FIELDS, PERSONA_DEFAULTS,
    PERSONA_EVENT_FIELDS, PERSONA_ML_FIELDS, PERSONA_STATUS_FIELDS,
    PRIVILEGE_CHANGE_FIELDS, ArchiveError, CdEDBLog, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, DeletionBlockers, Error, PathLike, PrivilegeError, PsycoJson,
    QuotaException, Realm, RequestState, Role, User, decode_parameter, encode_parameter,
    extract_realms, extract_roles, get_hash, glue, implied_realms, merge_dicts, n_, now,
    privilege_tier, unwrap, xsorted,
)
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import Atomizer, connection_pool_factory
from cdedb.query import Query, QueryOperators
from cdedb.validation import validate_check, validate_is


class CoreBackend(AbstractBackend):
    """Access to this is probably necessary from everywhere, so we need
    ``@internal`` quite often. """
    realm = "core"

    def __init__(self, configpath: PathLike = None) -> None:
        super().__init__(configpath)
        secrets = SecretsConfig(configpath)
        self.connpool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
            secrets, self.conf["DB_PORT"])
        # local variable to prevent closure over secrets
        reset_salt = secrets["RESET_SALT"]
        self.generate_reset_cookie = (
            lambda rs, persona_id, timeout: self._generate_reset_cookie(
                rs, persona_id, reset_salt, timeout=timeout))
        self.verify_reset_cookie = (
            lambda rs, persona_id, cookie: self._verify_reset_cookie(
                rs, persona_id, reset_salt, cookie))
        self.foto_dir: Path = self.conf['STORAGE_DIR'] / 'foto'
        self.genesis_attachment_dir: Path = (
                self.conf['STORAGE_DIR'] / 'genesis_attachment')

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    @access("persona")
    def is_relative_admin(self, rs: RequestState, persona_id: int,
                          allow_meta_admin: bool = False) -> bool:
        """Check whether the user is privileged with respect to a persona.

        A mailinglist admin may not edit cde users, but the other way
        round it should work.

        :param allow_meta_admin: In some cases we need to allow meta admins
            access where they should not normally have it. This is to allow that
            override.
        """
        if self.is_admin(rs):
            return True
        if allow_meta_admin and "meta_admin" in rs.user.roles:
            return True
        roles = extract_roles(unwrap(self.get_personas(rs, (persona_id,))),
                              introspection_only=True)
        return any(admin <= rs.user.roles for admin in privilege_tier(roles))

    @access("persona")
    def is_relative_admin_view(self, rs: RequestState, persona_id: int,
                               allow_meta_admin: bool = False) -> bool:
        """Check whether the user has the right admin views activated.

        This must not be used as privilege check, but only for hiding
        information which the user can view anyway.

        :param allow_meta_admin: In some cases we need to allow meta admins
            access where they should not normally have it. This is to allow that
            override.
        """
        if allow_meta_admin and "meta_admin" in rs.user.admin_views:
            return True
        roles = extract_roles(unwrap(self.get_personas(rs, (persona_id,))),
                              introspection_only=True)
        return any(
            admin_views <= {v.replace('_user', '_admin')
                            for v in rs.user.admin_views}
            for admin_views in privilege_tier(roles))

    def verify_persona_password(self, rs: RequestState, password: str,
                                persona_id: int) -> bool:
        """Helper to retrieve a personas password hash and verify the password.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        password_hash = unwrap(self.sql_select_one(
            rs, "core.personas", ("password_hash",), persona_id))
        if password_hash is None:
            return False
        return self.verify_password(password, password_hash)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Central function, so that the actual implementation may be easily
        changed.
        """
        return sha512_crypt.verify(password, password_hash)

    @staticmethod
    def encrypt_password(password: str) -> str:
        """We currently use passlib for password protection."""
        return sha512_crypt.hash(password)

    @staticmethod
    def create_fulltext(persona: CdEDBObject) -> str:
        """Helper to mangle all data into a single string.

        :param persona: one persona data set to convert into a string for
          fulltext search
        """
        attributes = (
            "title", "username", "display_name", "given_names",
            "family_name", "birth_name", "name_supplement", "birthday",
            "telephone", "mobile", "address_supplement", "address",
            "postal_code", "location", "country", "address_supplement2",
            "address2", "postal_code2", "location2", "country2", "weblink",
            "specialisation", "affiliation", "timeline", "interests",
            "free_form")
        values = (str(persona[a]) for a in attributes if persona[a] is not None)
        return " ".join(values)

    def core_log(self, rs: RequestState, code: const.CoreLogCodes,
                 persona_id: int = None, change_note: str = None,
                 atomized: bool = True) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param atomized: Whether this function should enforce an atomized context
            to be present.
         """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization by default.
        if atomized:
            self.affirm_atomized_context(rs)
        # do not use sql_insert since it throws an error for selecting the id
        query = ("INSERT INTO core.log "
                 "(code, submitted_by, persona_id, change_note) "
                 "VALUES (%s, %s, %s, %s)")
        return self.query_exec(
            rs, query, (code, rs.user.persona_id, persona_id, change_note))

    @internal
    @access("cde")
    def finance_log(self, rs: RequestState, code: const.FinanceLogCodes,
                    persona_id: Optional[int], delta: Optional[decimal.Decimal],
                    new_balance: Optional[decimal.Decimal],
                    change_note: str = None) -> DefaultReturnCode:
        """Make an entry in the finance log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param delta: change of balance
        :param new_balance: balance of user after the transaction
        """
        if rs.is_quiet:
            self.logger.warning("Finance log was suppressed.")
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        data = {
            "code": code,
            "submitted_by": rs.user.persona_id,
            "persona_id": persona_id,
            "delta": delta,
            "new_balance": new_balance,
            "change_note": change_note
        }
        with Atomizer(rs):
            query = """
                SELECT COUNT(*) AS members, COALESCE(SUM(balance), 0) AS total
                FROM core.personas
                WHERE is_member = True"""
            tmp = self.query_one(rs, query, tuple())
            if tmp:
                data.update(tmp)
            else:
                self.logger.error(f"Could not determine member count and total"
                                  f" balance for creating log entry {data!r}.")
                data.update(members=0, total=0)
            return self.sql_insert(rs, "cde.finance_log", data)

    @access("core_admin")
    def retrieve_log(self, rs: RequestState,
                     codes: Collection[const.CoreLogCodes] = None,
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
            rs, const.CoreLogCodes, "persona", "core.log", codes=codes,
            offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, change_note=change_note,
            time_start=time_start, time_stop=time_stop)

    @access("core_admin")
    def retrieve_changelog_meta(
            self, rs: RequestState,
            stati: Collection[const.MemberChangeStati] = None,
            offset: int = None, length: int = None, persona_id: int = None,
            submitted_by: int = None, change_note: str = None,
            time_start: datetime.datetime = None,
            time_stop: datetime.datetime = None,
            reviewed_by: int = None) -> CdEDBLog:
        """Get changelog activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        return self.generic_retrieve_log(
            rs, const.MemberChangeStati, "persona", "core.changelog",
            codes=stati, offset=offset, length=length, persona_id=persona_id,
            submitted_by=submitted_by, reviewed_by=reviewed_by,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    def changelog_submit_change(self, rs: RequestState, data: CdEDBObject,
                                generation: Optional[int], may_wait: bool,
                                change_note: str) -> DefaultReturnCode:
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
            if (current_state['code']
                    == const.MemberChangeStati.pending):
                committed_state = unwrap(self.get_total_personas(
                    rs, (data['id'],)))
                # stash pending change if we may not wait
                if not may_wait:
                    diff = {key: current_state[key] for key in committed_state
                            if committed_state[key] != current_state[key]}
                    current_state.update(committed_state)
                    query = glue("UPDATE core.changelog SET code = %s",
                                 "WHERE persona_id = %s AND code = %s")
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
                    query = glue("UPDATE core.changelog SET code = %s",
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
                     or (current_state['code']
                         == const.MemberChangeStati.pending and not diff))
                    and current_state['is_cde_realm']
                    and not ({"core_admin", "cde_admin"} & rs.user.roles))

            # prepare for inserting a new changelog entry
            query = glue("SELECT MAX(generation) AS gen FROM core.changelog",
                         "WHERE persona_id = %s")
            max_gen = unwrap(self.query_one(rs, query, (data['id'],))) or 1
            next_generation = max_gen + 1
            # the following is a nop, if there is no pending change
            query = glue("UPDATE core.changelog SET code = %s",
                         "WHERE persona_id = %s AND code = %s")
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
                "code": const.MemberChangeStati.pending,
                "persona_id": data['id'],
            })
            del insert['id']
            if 'ctime' in insert:
                del insert['ctime']
            self.sql_insert(rs, "core.changelog", insert)

            # resolve change if it doesn't require review
            if not requires_review or self.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                ret = self._changelog_resolve_change_unsafe(
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
                    "code": const.MemberChangeStati.pending,
                    "persona_id": data['id'],
                    "change_note": "Verdrängte Änderung.",
                })
                del insert['id']
                self.sql_insert(rs, "core.changelog", insert)
        return ret

    def _changelog_resolve_change_unsafe(
            self, rs: RequestState, persona_id: int, generation: int, ack: bool,
            reviewed: bool = True) -> DefaultReturnCode:
        """Review a currently pending change from the changelog.

        In practice most changes should be commited without review, so
        that the reviewers won't get plagued too much.

        :param ack: whether to commit or refuse the change
        :param reviewed: Signals wether the change was reviewed. This exists,
          so that automatically resolved changes are not marked as reviewed.
        """
        if not ack:
            query = glue(
                "UPDATE core.changelog SET reviewed_by = %s,",
                "code = %s",
                "WHERE persona_id = %s AND code = %s",
                "AND generation = %s")
            return self.query_exec(rs, query, (
                rs.user.persona_id, const.MemberChangeStati.nacked, persona_id,
                const.MemberChangeStati.pending, generation))
        with Atomizer(rs):
            # look up changelog entry and mark as committed
            history = self.changelog_get_history(rs, persona_id,
                                                 generations=(generation,))
            data = history[generation]
            if data['code'] != const.MemberChangeStati.pending:
                return 0
            query = "UPDATE core.changelog SET {setters} WHERE {conditions}"
            setters = ["code = %s"]
            params: List[Any] = [const.MemberChangeStati.committed]
            if reviewed:
                setters.append("reviewed_by = %s")
                params.append(rs.user.persona_id)
            conditions = ["persona_id = %s", "generation = %s"]
            params.extend([persona_id, generation])
            query = query.format(setters=', '.join(setters),
                                 conditions=' AND '.join(conditions))
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
    changelog_resolve_change = access("core_admin", "cde_admin")(
        _changelog_resolve_change_unsafe)

    @access("persona")
    def changelog_get_generations(self, rs: RequestState,
                                  ids: Collection[int]) -> Dict[int, int]:
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :returns: dict mapping ids to generations
        """
        query = glue("SELECT persona_id, max(generation) AS generation",
                     "FROM core.changelog WHERE persona_id = ANY(%s)",
                     "AND code = ANY(%s) GROUP BY persona_id")
        valid_status = (const.MemberChangeStati.pending,
                        const.MemberChangeStati.committed)
        data = self.query_all(rs, query, (ids, valid_status))
        return {e['persona_id']: e['generation'] for e in data}

    class _ChangelogGetGenerationProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> int: ...
    changelog_get_generation: _ChangelogGetGenerationProtocol = singularize(
        changelog_get_generations)

    @access("core_admin")
    def changelog_get_changes(self, rs: RequestState,
                              stati: Collection[const.MemberChangeStati]
                              ) -> CdEDBObjectMap:
        """Retrieve changes in the changelog."""
        stati = affirm_set(const.MemberChangeStati, stati)
        query = glue("SELECT id, persona_id, given_names, family_name,",
                     "generation, ctime",
                     "FROM core.changelog WHERE code = ANY(%s)")
        data = self.query_all(rs, query, (stati,))
        # TDOD what if there are multiple entries for one persona???
        return {e['persona_id']: e for e in data}

    @access("persona")
    def changelog_get_history(self, rs: RequestState, persona_id: int,
                              generations: Optional[Collection[int]]
                              ) -> CdEDBObjectMap:
        """Retrieve history of a data set.

        :parameter generations: generations to retrieve, all if None
        """
        persona_id = affirm(vtypes.ID, persona_id)
        if (persona_id != rs.user.persona_id
                and not self.is_relative_admin(
                rs, persona_id, allow_meta_admin=True)):
            raise PrivilegeError(n_("Not privileged."))
        generations = affirm_set(int, generations or set())
        fields = list(PERSONA_ALL_FIELDS)
        fields.remove('id')
        fields.append("persona_id AS id")
        fields.extend(("submitted_by", "reviewed_by", "ctime", "generation",
                       "code", "change_note"))
        query = "SELECT {fields} FROM core.changelog WHERE {conditions}"
        conditions = ["persona_id = %s"]
        params: List[Any] = [persona_id]
        if generations:
            conditions.append("generation = ANY(%s)")
            params.append(generations)
        query = query.format(fields=', '.join(fields),
                             conditions=' AND '.join(conditions))
        data = self.query_all(rs, query, params)
        return {e['generation']: e for e in data}

    @internal
    @access("persona", "droid")
    def retrieve_personas(self, rs: RequestState, persona_ids: Collection[int],
                          columns: Tuple[str, ...] = PERSONA_CORE_FIELDS
                          ) -> CdEDBObjectMap:
        """Helper to access a persona dataset.

        Most of the time a higher level function like
        :py:meth:`get_personas` should be used.
        """
        if "id" not in columns:
            columns += ("id",)
        data = self.sql_select(rs, "core.personas", columns, persona_ids)
        return {d['id']: d for d in data}

    class _RetrievePersonaProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int,
                     columns: Tuple[str, ...] = PERSONA_CORE_FIELDS) -> CdEDBObject: ...
    retrieve_persona: _RetrievePersonaProtocol = singularize(
        retrieve_personas, "persona_ids", "persona_id")

    @internal
    @access("ml")
    def list_all_personas(self, rs: RequestState, is_active: bool = False,
                          valid_email: bool = False) -> Set[int]:
        query = "SELECT id from core.personas WHERE is_archived = False"
        if is_active:
            query += " AND is_active = True"
        if valid_email:
            query += " AND username IS NOT NULL"
        data = self.query_all(rs, query, params=tuple())
        return {e["id"] for e in data}

    @internal
    @access("ml")
    def list_current_members(self, rs: RequestState, is_active: bool = False,
                             valid_email: bool = False) -> Set[int]:
        """Helper to list all current members.

        Used to determine subscribers of mandatory/opt-out member mailinglists.
        """
        query = "SELECT id from core.personas WHERE is_member = True"
        if is_active:
            query += " AND is_active = True"
        if valid_email:
            query += " AND username IS NOT NULL"
        data = self.query_all(rs, query, params=tuple())
        return {e["id"] for e in data}

    @internal
    @access("ml")
    def list_all_moderators(self, rs: RequestState,
                            ml_types: Optional[Collection[const.MailinglistTypes]] = None
                            ) -> Set[int]:
        """List all moderators of any mailinglists.

        Due to architectural limitations of the BackendContainer used for
        mailinglist types, this is found here instead of in the MlBackend.
        """
        query = "SELECT DISTINCT mod.persona_id from ml.moderators as mod"
        if ml_types:
            query += (" JOIN ml.mailinglists As ml ON mod.mailinglist_id = ml.id"
                      " WHERE ml.ml_type = ANY(%s)")
        data = self.query_all(rs, query, params=(ml_types,))
        return {e["persona_id"] for e in data}

    @access("core_admin")
    def next_persona(self, rs: RequestState, persona_id: Optional[int], *,
                     is_member: Optional[bool],
                     is_archived: Optional[bool]) -> Optional[int]:
        """Look up the following persona.

        :param is_member: If not None, only consider personas with a matching flag.
        :param is_archived: If not None, only consider personas with a matching flag.

        :returns: Next valid id in table core.personas
        """
        persona_id = affirm_optional(int, persona_id)
        is_member = affirm_optional(bool, is_member)
        is_archived = affirm_optional(bool, is_archived)
        query = "SELECT MIN(id) FROM core.personas"
        constraints = []
        params: List[Any] = []
        if persona_id is not None:
            constraints.append("id > %s")
            params.append(persona_id)
        if is_member is not None:
            constraints.append("is_member = %s")
            params.append(is_member)
        if is_archived is not None:
            constraints.append("is_archived = %s")
            params.append(is_archived)
        query += " WHERE " + " AND ".join(constraints)
        return unwrap(self.query_one(rs, query, params))

    def commit_persona(self, rs: RequestState, data: CdEDBObject,
                       change_note: Optional[str]) -> DefaultReturnCode:
        """Actually update a persona data set.

        This is the innermost layer of the changelog functionality and
        actually modifies the core.personas table.
        """
        with Atomizer(rs):
            num = self.sql_update(rs, "core.personas", data)
            if not num:
                raise ValueError(n_("Nonexistent user."))
            current = unwrap(self.retrieve_personas(
                rs, (data['id'],), columns=PERSONA_ALL_FIELDS))
            fulltext = self.create_fulltext(current)
            fulltext_update = {
                'id': data['id'],
                'fulltext': fulltext
            }
            self.sql_update(rs, "core.personas", fulltext_update)
        return num

    @internal
    @access("persona")
    def set_persona(self, rs: RequestState, data: CdEDBObject,
                    generation: int = None, change_note: str = None,
                    may_wait: bool = True,
                    allow_specials: Tuple[str, ...] = tuple()
                    ) -> DefaultReturnCode:
        """Internal helper for modifying a persona data set.

        Most of the time a higher level function like
        :py:meth:`change_persona` should be used.

        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :param may_wait: Whether this change may wait in the changelog. If
          this is ``False`` and there is a pending change in the changelog,
          the new change is slipped in between.
        :param allow_specials: Protect some attributes against accidential
          modification. A magic value has to be passed in this array to
          allow modification. This is done by special methods like
          :py:meth:`change_foto` which take care that the necessary
          prerequisites are met.
        :param change_note: Comment to record in the changelog entry. This
          is ignored if the persona is not in the changelog.
        """
        if not change_note:
            self.logger.info(
                "No change note specified (persona_id={}).".format(data['id']))
            change_note = "Allgemeine Änderung"

        current = self.sql_select_one(
            rs, "core.personas", ("is_archived", "decided_search"), data['id'])
        if current is None:
            raise ValueError(n_("Persona does not exist."))
        if not may_wait and generation is not None:
            raise ValueError(
                n_("Non-waiting change without generation override."))
        realm_keys = {'is_cde_realm', 'is_event_realm', 'is_ml_realm',
                      'is_assembly_realm'}
        if (set(data) & realm_keys
                and ("core_admin" not in rs.user.roles
                     or not {"realms", "purge"} & set(allow_specials))):
            raise PrivilegeError(n_("Realm modification prevented."))
        if (set(data) & ADMIN_KEYS
                and ("meta_admin" not in rs.user.roles
                     or "admins" not in allow_specials)):
            if any(data[key] for key in ADMIN_KEYS):
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
            # Allow setting balance to 0 or None during archival.
            if not ((data["balance"] is None or data["balance"] == 0)
                    and "archive" in allow_specials):
                raise PrivilegeError(n_("Modification of balance prevented."))
        if "username" in data and "username" not in allow_specials:
            raise PrivilegeError(n_("Modification of email address prevented."))
        if "foto" in data and "foto" not in allow_specials:
            raise PrivilegeError(n_("Modification of foto prevented."))
        if data.get("is_active") and rs.user.persona_id == data['id']:
            raise PrivilegeError(n_("Own activation prevented."))

        # check for permission to edit
        allow_meta_admin = data.keys() <= ADMIN_KEYS | {"id"}
        if (rs.user.persona_id != data['id']
                and not self.is_relative_admin(rs, data['id'],
                                               allow_meta_admin)):
            raise PrivilegeError(n_("Not privileged."))

        # Prevent modification of archived members. This check is
        # sufficient since we can only edit our own data if we are not
        # archived.
        if (current['is_archived'] and data.get('is_archived', True)
                and "purge" not in allow_specials):
            raise RuntimeError(n_("Editing archived member impossible."))

        with Atomizer(rs):
            ret = self.changelog_submit_change(
                rs, data, generation=generation,
                may_wait=may_wait, change_note=change_note)
            if allow_specials and ret < 0:
                raise RuntimeError(n_("Special change not committed."))
            return ret

    @access("persona")
    def change_persona(self, rs: RequestState, data: CdEDBObject,
                       generation: int = None, may_wait: bool = True,
                       change_note: str = None,
                       ignore_warnings: bool = False) -> DefaultReturnCode:
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :param may_wait: override for system requests (which may not wait)
        :param change_note: Descriptive line for changelog
        :param ignore_warnings: Ignore errors of type ValidationWarning.
        """
        data = affirm(vtypes.Persona, data, _ignore_warnings=ignore_warnings)
        generation = affirm_optional(int, generation)
        may_wait = affirm(bool, may_wait)
        change_note = affirm_optional(str, change_note)
        return self.set_persona(rs, data, generation=generation,
                                may_wait=may_wait, change_note=change_note)

    @access("core_admin")
    def change_persona_realms(self, rs: RequestState,
                              data: CdEDBObject) -> DefaultReturnCode:
        """Special modification function for realm transitions."""
        data = affirm(vtypes.Persona, data, transition=True)
        with Atomizer(rs):
            if data.get('is_cde_realm'):
                # Fix balance
                tmp = unwrap(self.get_total_personas(rs, (data['id'],)))
                if tmp['balance'] is None:
                    data['balance'] = decimal.Decimal('0.0')
                else:
                    data['balance'] = tmp['balance']
            ret = self.set_persona(
                rs, data, may_wait=False,
                change_note="Bereiche geändert.",
                allow_specials=("realms", "finance", "membership"))
            if data.get('trial_member'):
                ret *= self.change_membership(rs, data['id'], is_member=True)
            self.core_log(
                rs, const.CoreLogCodes.realm_change, data['id'],
                change_note="Bereiche geändert.")
            return ret

    @access("persona")
    def change_foto(self, rs: RequestState, persona_id: int,
                    foto: Optional[bytes]) -> DefaultReturnCode:
        """Special modification function for foto changes.

        Return 1 on successful change, -1 on successful removal, 0 otherwise.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        foto = affirm_optional(vtypes.ProfilePicture, foto, file_storage=False)
        data: CdEDBObject
        if foto is None:
            with Atomizer(rs):
                old_hash = unwrap(self.sql_select_one(
                    rs, "core.personas", ("foto",), persona_id))
                data = {
                    'id': persona_id,
                    'foto': None,
                }
                ret = self.set_persona(
                    rs, data, may_wait=False,
                    change_note="Profilbild entfernt.",
                    allow_specials=("foto",))
                # Return a negative value to signify deletion.
                if ret < 0:
                    raise RuntimeError("Special persona change should not"
                                       " be pending.")
                ret = -1 * ret
                if ret and old_hash and not self.foto_usage(rs, old_hash):
                    path = self.foto_dir / old_hash
                    if path.exists():
                        path.unlink()
        else:
            my_hash = get_hash(foto)
            data = {
                'id': persona_id,
                'foto': my_hash,
            }
            ret = self.set_persona(
                rs, data, may_wait=False, change_note="Profilbild geändert.",
                allow_specials=("foto",))
            if ret:
                path = self.foto_dir / my_hash
                if not path.exists():
                    with open(path, 'wb') as f:
                        f.write(foto)
        return ret

    @access("persona")
    def get_foto(self, rs: RequestState, foto: str) -> Optional[bytes]:
        """Retrieve a stored foto.

        The foto is identified by its hash rather than the persona id it
         belongs to, to prevent scraping."""
        foto = affirm(str, foto)
        path = self.foto_dir / foto
        ret = None
        if path.exists():
            with open(path, "rb") as f:
                ret = f.read()
        return ret

    @access("meta_admin")
    def initialize_privilege_change(self, rs: RequestState,
                                    data: CdEDBObject) -> DefaultReturnCode:
        """Initialize a change to a users admin bits.

        This has to be approved by another admin.
        """
        data['submitted_by'] = rs.user.persona_id
        data['status'] = const.PrivilegeChangeStati.pending
        data = affirm(vtypes.PrivilegeChange, data)

        with Atomizer(rs):
            if ("is_meta_admin" in data
                    and data['persona_id'] == rs.user.persona_id):
                raise PrivilegeError(n_(
                    "Cannot modify own meta admin privileges."))
            if self.list_privilege_changes(
                    rs, persona_id=data['persona_id'],
                    stati=(const.PrivilegeChangeStati.pending,)):
                raise ValueError(n_("Pending privilege change."))

            persona = unwrap(self.get_total_personas(rs, (data['persona_id'],)))

            # see also cdedb.frontend.templates.core.change_privileges
            # and change_privileges in cdedb.frontend.core

            errormsg = n_("User does not fit the requirements for this"
                          " admin privilege.")
            realms = {"cde", "event", "ml", "assembly"}
            for realm in realms:
                if not persona['is_{}_realm'.format(realm)]:
                    if data.get('is_{}_admin'.format(realm)):
                        raise ValueError(errormsg)

            if data.get('is_finance_admin'):
                if (data.get('is_cde_admin') is False
                    or (not persona['is_cde_admin']
                        and not data.get('is_cde_admin'))):
                    raise ValueError(errormsg)

            if data.get('is_core_admin') or data.get('is_meta_admin'):
                if not persona['is_cde_realm']:
                    raise ValueError(errormsg)

            if data.get('is_cdelokal_admin'):
                if not persona['is_ml_realm']:
                    raise ValueError(errormsg)

            self.core_log(
                rs, const.CoreLogCodes.privilege_change_pending,
                data['persona_id'],
                change_note="Änderung der Admin-Privilegien angestoßen.")
            ret = self.sql_insert(rs, "core.privilege_changes", data)

        return ret

    @access("meta_admin")
    def finalize_privilege_change(self, rs: RequestState, privilege_change_id: int,
                                  case_status: const.PrivilegeChangeStati
                                  ) -> DefaultReturnCode:
        """Finalize a pending change to a users admin bits.

        This has to be done by a different admin.

        If the user had no admin privileges previously, we require a password
        reset afterwards.

        :returns: default return code. A negative return indicates, that the
            users password was invalidated and will need to be changed.
        """
        privilege_change_id = affirm(vtypes.ID, privilege_change_id)
        case_status = affirm(const.PrivilegeChangeStati, case_status)

        data = {
            "id": privilege_change_id,
            "ftime": now(),
            "reviewer": rs.user.persona_id,
            "status": case_status,
        }
        with Atomizer(rs):
            case = self.get_privilege_change(rs, privilege_change_id)
            if case['status'] != const.PrivilegeChangeStati.pending:
                raise ValueError(
                    n_("Invalid privilege change state: %(status)s."),
                    {"status": case["status"]})
            if case_status == const.PrivilegeChangeStati.approved:
                if (case["is_meta_admin"] is not None
                        and case['persona_id'] == rs.user.persona_id):
                    raise PrivilegeError(
                        n_("Cannot modify own meta admin privileges."))
                if case['submitted_by'] == rs.user.persona_id:
                    raise PrivilegeError(
                        n_("Only a different admin than the submitter "
                           "may approve a privilege change."))

                ret = self.sql_update(rs, "core.privilege_changes", data)

                self.core_log(
                    rs, const.CoreLogCodes.privilege_change_approved,
                    persona_id=case['persona_id'],
                    change_note="Änderung der Admin-Privilegien bestätigt.")

                old = self.get_persona(rs, case["persona_id"])
                data = {
                    "id": case["persona_id"]
                }
                for key in ADMIN_KEYS:
                    if case[key] is not None:
                        data[key] = case[key]

                data = affirm(vtypes.Persona, data)
                note = ("Admin-Privilegien geändert."
                        if not case["notes"] else case["notes"])
                ret *= self.set_persona(
                    rs, data, may_wait=False,
                    change_note=note, allow_specials=("admins",))

                # Force password reset if non-admin has gained admin privileges.
                if (not any(old[key] for key in ADMIN_KEYS)
                        and any(data.get(key) for key in ADMIN_KEYS)):
                    ret *= self.invalidate_password(rs, case["persona_id"])
                    ret *= -1

                # Mark case as successful
                data = {
                    "id": privilege_change_id,
                    "status": const.PrivilegeChangeStati.successful,
                }
                ret *= self.sql_update(rs, "core.privilege_changes", data)

            elif case_status == const.PrivilegeChangeStati.rejected:
                ret = self.sql_update(rs, "core.privilege_changes", data)

                self.core_log(
                    rs, const.CoreLogCodes.privilege_change_rejected,
                    persona_id=case['persona_id'],
                    change_note="Änderung der Admin-Privilegien verworfen.")
            else:
                raise ValueError(n_("Invalid new privilege change status."))

        return ret

    @access("meta_admin")
    def list_privilege_changes(self, rs: RequestState, persona_id: int = None,
                               stati: Collection[
                                   const.PrivilegeChangeStati] = None
                               ) -> CdEDBObjectMap:
        """List privilge changes.

        Can be restricted to certain stati.

        :param persona_id: limit to this persona id.
        :returns: dict mapping case ids to dicts containing information about
            the change
        """
        persona_id = affirm_optional(vtypes.ID, persona_id)
        stati = stati or set()
        stati = affirm_set(const.PrivilegeChangeStati, stati)

        query = "SELECT id, persona_id, status FROM core.privilege_changes"
        constraints = []
        params: List[Any] = []
        if persona_id:
            constraints.append("persona_id = %s")
            params.append(persona_id)
        if stati:
            constraints.append("status = ANY(%s)")
            params.append(stati)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)
        return {e["id"]: e for e in data}

    @access("meta_admin")
    def get_privilege_changes(self, rs: RequestState,
                              privilege_change_ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve datasets for priviledge changes."""
        privilege_change_ids = affirm_set(vtypes.ID, privilege_change_ids)
        data = self.sql_select(
            rs, "core.privilege_changes", PRIVILEGE_CHANGE_FIELDS, privilege_change_ids)
        return {e["id"]: e for e in data}

    class _GetPrivilegeChangeProtocol(Protocol):
        def __call__(self, rs: RequestState, privilege_change_id: int
                     ) -> CdEDBObject: ...
    get_privilege_change: _GetPrivilegeChangeProtocol = singularize(
        get_privilege_changes, "privilege_change_ids", "privilege_change_id")

    @access("persona")
    def list_admins(self, rs: RequestState, realm: str) -> List[int]:
        """List all personas with admin privilidges in a given realm.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type realm: str
        :rtype: [int]
        """
        realm = affirm(str, realm)

        query = "SELECT id from core.personas WHERE {constraint}"

        constraints = {
            "meta": "is_meta_admin = TRUE",
            "core": "is_core_admin = TRUE",
            "cde": "is_cde_admin = TRUE",
            "finance": "is_finance_admin = TRUE",
            "event": "is_event_admin = TRUE",
            "ml": "is_ml_admin = TRUE",
            "assembly": "is_assembly_admin = TRUE",
            "cdelokal": "is_cdelokal_admin = TRUE",
        }
        constraint = constraints.get(realm)

        if constraint is None:
            raise ValueError(n_("No realm provided."))

        query = query.format(constraint=constraint)
        result = self.query_all(rs, query, tuple())

        return [e["id"] for e in result]

    @access("core_admin", "cde_admin")
    def change_persona_balance(self, rs: RequestState, persona_id: int,
                               balance: Union[str, decimal.Decimal],
                               log_code: const.FinanceLogCodes,
                               change_note: str = None,
                               trial_member: bool = None) -> DefaultReturnCode:
        """Special modification function for monetary aspects.

        :param trial_member: If not None, set trial membership to this.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        balance = affirm(vtypes.NonNegativeDecimal, balance)
        log_code = affirm(const.FinanceLogCodes, log_code)
        trial_member = affirm_optional(bool, trial_member)
        change_note = affirm_optional(str, change_note)
        update: CdEDBObject = {
            'id': persona_id,
        }
        with Atomizer(rs):
            current = unwrap(self.retrieve_personas(
                rs, (persona_id,), ("balance", "is_cde_realm", "trial_member")))
            if not current['is_cde_realm']:
                raise RuntimeError(
                    n_("Tried to credit balance to non-cde person."))
            if current['balance'] != balance:
                update['balance'] = balance
            if trial_member is not None:
                if current['trial_member'] != trial_member:
                    update['trial_member'] = trial_member
            if 'balance' in update or 'trial_member' in update:
                ret = self.set_persona(
                    rs, update, may_wait=False, change_note=change_note,
                    allow_specials=("finance",))
                if 'balance' in update:
                    self.finance_log(rs, log_code, persona_id,
                                     balance - current['balance'], balance)
                return ret
            else:
                return 0

    @access("core_admin", "cde_admin")
    def change_membership(self, rs: RequestState, persona_id: int,
                          is_member: bool) -> DefaultReturnCode:
        """Special modification function for membership."""
        persona_id = affirm(vtypes.ID, persona_id)
        is_member = affirm(bool, is_member)
        update: CdEDBObject = {
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
                new_balance = None  # type: ignore
                code = const.FinanceLogCodes.gain_membership
            ret = self.set_persona(
                rs, update, may_wait=False,
                change_note="Mitgliedschaftsstatus geändert.",
                allow_specials=("membership", "finance"))
            self.finance_log(rs, code, persona_id, delta, new_balance)
            return ret

    @access("core_admin", "meta_admin")
    def invalidate_password(self, rs: RequestState,
                            persona_id: int) -> DefaultReturnCode:
        """Replace a users password with an unknown one.

        This forces the user to set a new password and also invalidates all
        current sessions.

        This is to be used when granting admin privileges to a user who has
        not previously had any, hence we allow backend access for all
        meta_admins.
        """
        persona_id = affirm(vtypes.ID, persona_id)

        # modified version of hash for 'secret' and thus
        # safe/unknown plaintext
        password_hash = (
            "$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
            "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHE/si/")
        query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"

        with Atomizer(rs):
            ret = self.query_exec(rs, query, (password_hash, persona_id))

            # Invalidate alle active sessions.
            query = ("UPDATE core.sessions SET is_active = False "
                     "WHERE persona_id = %s AND is_active = True")
            self.query_exec(rs, query, (persona_id,))

            self.core_log(rs, code=const.CoreLogCodes.password_invalidated,
                          persona_id=persona_id)

        return ret

    @access("core_admin")
    def get_persona_latest_session(self, rs: RequestState, persona_id: int
                                   ) -> Optional[datetime.datetime]:
        """Retrieve the time of a users latest session.

        Returns None if there are no active sessions on record.
        """
        persona_id = affirm(vtypes.ID, persona_id)

        query = "SELECT MAX(atime) AS atime FROM core.sessions WHERE persona_id = %s"
        return unwrap(self.query_one(rs, query, (persona_id,)))

    @access("core_admin")
    def is_persona_automatically_archivable(self, rs: RequestState, persona_id: int,
                                            reference_date: datetime.date = None
                                            ) -> bool:
        """Determine whether a persona is eligble to be automatically archived.

        :param reference_date: If given consider this as the reference point for
            determining inactivity. Otherwise use the current date. Either way this
            calculates the actual cutoff using a config parameter. This is intended
            to be used during semester management to send notifications during step 1
            and later archive those who were previosly notified, not those who turned
            eligible for archival in between.

        Things that prevent such automated archival:
            * The persona having any admin bit.
            * The persona being a member.
            * The persona already being archived.
            * The persona having logged in in the last two years.
            * The persona having been changed/created in the last two years.
            * The persona being involved (orga/registration) with any recent event.
            * The persona being involved (presider/attendee) with an active assembly.
            * The persona being explicitly subscribed to any mailinglist.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        reference_date = affirm(datetime.date, reference_date or now().date())

        cutoff = reference_date - self.conf["AUTOMATED_ARCHIVAL_CUTOFF"]
        with Atomizer(rs):
            persona = self.get_persona(rs, persona_id)

            # Do some basic sanity checks.
            if any(persona[admin_key] for admin_key in ADMIN_KEYS):
                return False

            if persona['is_member'] or persona['is_archived']:
                return False

            # Check latest user session.
            latest_session = self.get_persona_latest_session(rs, persona_id)
            if latest_session is not None and latest_session > cutoff:
                return False

            generation = self.changelog_get_generation(rs, persona_id)
            history = self.changelog_get_history(rs, persona_id, (generation,))
            last_change = history[generation]
            if last_change['ctime'].date() > cutoff:
                return False

            # Check event involvement.
            # TODO use 'is_archived' instead of 'event_end'?
            query = """SELECT MAX(part_end) AS event_end
            FROM (
                (
                    SELECT event_id
                    FROM event.registrations
                    WHERE persona_id = %s
                    UNION
                    SELECT event_id
                    FROM event.orgas
                    WHERE persona_id = %s
                ) as ids
                JOIN event.event_parts ON ids.event_id = event_parts.event_id
            )
            """
            event_end = unwrap(self.query_one(rs, query, (persona_id, persona_id)))
            if event_end and event_end > cutoff:
                return False

            # Check assembly involvement
            query = """SELECT assembly_id
            FROM (
                (
                    SELECT assembly_id
                    FROM assembly.attendees
                    WHERE persona_id = %s
                    UNION
                    SELECT assembly_id
                    FROM assembly.presiders
                    WHERE persona_id = %s
                ) AS ids
                JOIN assembly.assemblies ON ids.assembly_id = assemblies.id
            )
            WHERE assemblies.is_active = True"""
            if self.query_all(rs, query, (persona_id, persona_id)):
                return False

            # Check mailinglist subscriptions.
            # TODO don't hardcode subscription states here?
            query = """SELECT mailinglist_id
            FROM ml.subscription_states AS ss
            JOIN ml.mailinglists ON ss.mailinglist_id = mailinglists.id
            WHERE persona_id = %s AND subscription_state = ANY(%s)
                AND mailinglists.is_active = True"""
            states = {
                const.SubscriptionStates.subscribed,
                const.SubscriptionStates.subscription_override,
                const.SubscriptionStates.pending,
            }
            if self.query_all(rs, query, (persona_id, states)):
                return False

        return True

    @access("core_admin", "cde_admin")
    def archive_persona(self, rs: RequestState, persona_id: int,
                        note: str) -> DefaultReturnCode:
        """Move a persona to the attic.

        This clears most of the data we have about the persona. The
        basic use case is for retiring members of a time long gone,
        which have not been seen for an extended period.

        We keep the following data to enable us to recognize them
        later on to allow readmission:

        * name,
        * gender,
        * date of birth,
        * past events,
        * type of account (i.e. the realm bits).

        Additionally not all data is purged, since we have separate
        life cycles for different realms. This affects the following.

        * finances: we preserve a log of all transactions for bookkeeping,
        * lastschrift: similarily to finances
        * events: to ensure consistency, events are only deleted en bloc
        * assemblies: these we keep to make the decisions traceable
        """
        persona_id = affirm(vtypes.ID, persona_id)
        note = affirm(str, note)
        with Atomizer(rs):
            persona = unwrap(self.get_total_personas(rs, (persona_id,)))
            #
            # 1. Do some sanity checks.
            #
            if persona['is_archived']:
                return 0

            # Disallow archival of admins. Admin privileges should be unset
            # by two meta admins before.
            if any(persona[key] for key in ADMIN_KEYS):
                raise ArchiveError(n_("Cannot archive admins."))

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
                'is_meta_admin': False,
                'is_core_admin': False,
                'is_cde_admin': False,
                'is_finance_admin': False,
                'is_event_admin': False,
                'is_ml_admin': False,
                'is_assembly_admin': False,
                'is_cdelokal_admin': False,
                # Do no touch the realms, to preserve integrity and
                # allow reactivation.
                # 'is_cde_realm'
                # 'is_event_realm'
                # 'is_ml_realm'
                # 'is_assembly_realm'
                # 'is_member' already adjusted
                'is_searchable': False,
                # 'is_archived' will be done later
                # 'is_purged' not relevant here
                # 'display_name' kept for later recognition
                # 'given_names' kept for later recognition
                # 'family_name' kept for later recognition
                'title': None,
                'name_supplement': None,
                # 'gender' kept for later recognition
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
                'balance': 0 if persona['balance'] is not None else None,
                'decided_search': False,
                'trial_member': False,
                'bub_search': False,
                'paper_expuls': True,
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
            if any(not ls['revoked_at'] for ls in lastschrift):
                raise ArchiveError(n_("Active lastschrift exists."))
            query = ("UPDATE cde.lastschrift"
                     " SET (amount, iban, account_owner, account_address)"
                     " = (%s, %s, %s, %s)"
                     " WHERE persona_id = %s"
                     " AND revoked_at < now() - interval '14 month'")
            if lastschrift:
                self.query_exec(rs, query, (0, "", "", "", persona_id))
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
            self.sql_delete(rs, "ml.subscription_addresses", (persona_id,),
                            "persona_id")
            # Make sure the users moderatored mls will still have moderators.
            # Retrieve moderated mailinglists.
            query = ("SELECT ARRAY_AGG(mailinglist_id) FROM ml.moderators"
                     " WHERE persona_id = %s GROUP BY persona_id")
            moderated_mailinglists = set(unwrap(self.query_one(
                rs, query, (persona_id,))) or [])
            self.sql_delete(rs, "ml.moderators", (persona_id,), "persona_id")
            if moderated_mailinglists:
                # Retrieve the mailinglists, that _still_ have moderators.
                query = ("SELECT ARRAY_AGG(DISTINCT mailinglist_id) as ml_ids"
                         " FROM ml.moderators WHERE mailinglist_id = ANY(%s)")
                ml_ids = set(unwrap(self.query_one(
                    rs, query, (moderated_mailinglists,))) or [])
                # Check the difference.
                unmodearated_mailinglists = moderated_mailinglists - ml_ids
                if unmodearated_mailinglists:
                    raise ArchiveError(
                        n_("Sole moderator of a mailinglist {ml_ids}."),
                        {'ml_ids': unmodearated_mailinglists})
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
            self.core_log(rs, const.CoreLogCodes.persona_archived, persona_id)
            #
            # 11. Clear changelog
            #
            query = glue(
                "SELECT id FROM core.changelog WHERE persona_id = %s",
                "ORDER BY generation DESC LIMIT 1")
            newest = self.query_one(rs, query, (persona_id,))
            if not newest:
                # TODO do we want to allow this?
                # This could happen if this call is wrapped in a Silencer.
                raise ArchiveError(n_("Cannot archive silently."))
            query = ("DELETE FROM core.changelog"
                     " WHERE persona_id = %s AND NOT id = %s")
            ret = self.query_exec(rs, query, (persona_id, newest['id']))
            #
            # 12. Finish
            #
            return ret

    @access("core_admin")
    def dearchive_persona(self, rs: RequestState,
                          persona_id: int) -> DefaultReturnCode:
        """Return a persona from the attic to activity.

        This does nothing but flip the archiving bit.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :rtype: int
        :returns: default return code
        """
        persona_id = affirm(vtypes.ID, persona_id)
        with Atomizer(rs):
            update = {
                'id': persona_id,
                'is_archived': False,
            }
            code = self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer aus dem Archiv wiederhergestellt.",
                allow_specials=("archive",))
            self.core_log(rs, const.CoreLogCodes.persona_dearchived, persona_id)
            return code

    @access("core_admin", "cde_admin")
    def purge_persona(self, rs: RequestState,
                      persona_id: int) -> DefaultReturnCode:
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
        persona_id = affirm(vtypes.ID, persona_id)
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
                'birthday': "-Infinity",
                'birth_name': None,
                'gender': const.Genders.not_specified,
                'is_cde_realm': True,
                'is_event_realm': True,
                'is_ml_realm': True,
                'is_assembly_realm': True,
                'is_purged': True,
            }
            ret = self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer gelöscht.",
                allow_specials=("admins", "username", "purge"))
            #
            # 2. Remove past event data.
            #
            self.sql_delete(
                rs, "past_event.participants", (persona_id,), "persona_id")
            #
            # 3. Clear changelog
            #
            query = glue(
                "SELECT id FROM core.changelog WHERE persona_id = %s",
                "ORDER BY generation DESC LIMIT 1")
            newest = self.query_one(rs, query, (persona_id,))
            if not newest:
                # TODO allow this?
                raise ArchiveError(n_("Cannot purge silently."))
            query = glue(
                "DELETE FROM core.changelog",
                "WHERE persona_id = %s AND NOT id = %s")
            ret *= self.query_exec(rs, query, (persona_id, newest['id']))
            #
            # 4. Finish
            #
            self.core_log(rs, const.CoreLogCodes.persona_purged, persona_id)
            return ret

    @access("persona")
    def change_username(self, rs: RequestState, persona_id: int,
                        new_username: Optional[str], password: Optional[str]
                        ) -> Tuple[bool, str]:
        """Since usernames are used for login, this needs a bit of care.

        :returns: The bool signals whether the change was successful, the str
            is an error message or the new username on success.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        new_username = affirm_optional(vtypes.Email, new_username)
        password = affirm_optional(str, password)
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
                if self.verify_persona_password(rs, password, persona_id):
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
                    self.core_log(
                        rs, const.CoreLogCodes.username_change, persona_id,
                        change_note=new_username)
                    if new_username:
                        return True, new_username
                    else:
                        return True, n_("Username removed.")
        return False, n_("Failed.")

    @access("persona")
    def foto_usage(self, rs: RequestState, foto: str) -> int:
        """Retrieve usage number for a specific foto.

        So we know when a foto is up for garbage collection."""
        foto = affirm(str, foto)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE foto = %s"
        return unwrap(self.query_one(rs, query, (foto,))) or 0

    @access("persona")
    def get_personas(self, rs: RequestState, persona_ids: Collection[int]
                     ) -> CdEDBObjectMap:
        """Acquire data sets for specified ids."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        return self.retrieve_personas(rs, persona_ids, columns=PERSONA_CORE_FIELDS)

    class _GetPersonaProtocol(Protocol):
        # `persona_id` is actually not optional, but it produces a lot of errors.
        def __call__(self, rs: RequestState, persona_id: Optional[int]
                     ) -> CdEDBObject: ...
    get_persona: _GetPersonaProtocol = singularize(
        get_personas, "persona_ids", "persona_id")

    @access("event", "droid_quick_partial_export")
    def get_event_users(self, rs: RequestState, persona_ids: Collection[int],
                        event_id: int = None) -> CdEDBObjectMap:
        """Get an event view on some data sets.

        This is allowed for admins and for yourself in any case. Orgas can also
        query users registered for one of their events; other event users can
        query participants of events they participate themselves.

        :param event_id: allows all users which are registered to this event
            to query for other participants of the same event by their ids.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        event_id = affirm_optional(vtypes.ID, event_id)
        ret = self.retrieve_personas(rs, persona_ids, columns=PERSONA_EVENT_FIELDS)
        # The event user view on a cde user contains lots of personal
        # data. So we require the requesting user to be orga (to get access to
        # all event users who are related to their event) or 'participant'
        # of the requested event (to get access to all event users who are also
        # 'participant' at the same event).
        #
        # This is a bit of a transgression since we access the event
        # schema from the core backend, but we go for security instead of
        # correctness here.
        if event_id:
            orga = ("SELECT event_id FROM event.orgas WHERE persona_id = %s"
                    " AND event_id = %s")
            is_orga = bool(
                self.query_all(rs, orga, (rs.user.persona_id, event_id)))
        else:
            is_orga = False
        if (persona_ids != {rs.user.persona_id}
                and not (rs.user.roles
                         & {"event_admin", "cde_admin", "core_admin",
                            "droid_quick_partial_export"})):
            query = """
                SELECT DISTINCT
                    regs.id, regs.persona_id
                FROM
                    event.registrations AS regs
                    LEFT OUTER JOIN
                        event.registration_parts AS rparts
                    ON rparts.registration_id = regs.id
                WHERE
                    {conditions}"""
            conditions = ["regs.event_id = %s"]
            params: List[Any] = [event_id]
            if not is_orga:
                conditions.append("rparts.status = %s")
                params.append(const.RegistrationPartStati.participant)
            query = query.format(conditions=' AND '.join(conditions))
            data = self.query_all(rs, query, params)
            all_users_inscope = set(e['persona_id'] for e in data)
            same_event = set(ret) <= all_users_inscope
            if not (same_event and (is_orga or
                                    rs.user.persona_id in all_users_inscope)):
                raise PrivilegeError(n_("Access to persona data inhibited."))
        if any(not e['is_event_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an event user."))
        return ret

    class _GetEventUserProtocol(Protocol):
        # `persona_id` is actually not optional, but it produces a lot of errors.
        def __call__(self, rs: RequestState, persona_id: Optional[int],
                     event_id: int = None) -> CdEDBObject: ...
    get_event_user: _GetEventUserProtocol = singularize(
        get_event_users, "persona_ids", "persona_id")

    @overload
    def quota(self, rs: RequestState, *, ids: Collection[int]) -> int: ...

    @overload
    def quota(self, rs: RequestState, *, num: int) -> int: ...

    @overload
    def quota(self, rs: RequestState) -> int: ...

    @internal
    @access("persona")
    def quota(self, rs: RequestState, *, ids: Collection[int] = None,
              num: int = None) -> int:
        """Log quota restricted accesses. Return new total.

        This can optionally take either a list of ids or simply a number of
        restricted actions. Just return the total if no parameter was provided.

        A restricted action can be either:
            * Accessing the cde profile of another user.
            * A member search.

        We either insert the number of restricted actions into the quota table
        or add them if an entry already exists, as entries are unique across
        persona_id and date.

        Beware that this function can optionally be called in an atomized setting.
        If this is the case, the quota is not actually raised by the offending query,
        but access is blocked nonetheless. Otherwise, a value exceeding the quota limit
        is saved into the database, which means that actions that should still be
        possible need to be exempt in the check_quota function.

        :returns: Return the number of restricted actions the user has
            performed today including the ones given with this call, if any.
        """
        if ids is not None and num is not None:
            raise ValueError(n_("May not provide more than one input."))
        access_hash: Optional[str] = None
        if ids is not None:
            ids = affirm_set(vtypes.ID, ids or set()) - {rs.user.persona_id}
            num = len(ids)
            access_hash = get_hash(str(sorted(ids)).encode())
        else:
            num = affirm(vtypes.NonNegativeInt, num or 0)

        persona_id = rs.user.persona_id
        now_date = now().date()

        query = ("SELECT last_access_hash, queries FROM core.quota"
                 " WHERE persona_id = %s AND qdate = %s")
        data = self.query_one(rs, query, (persona_id, now_date))
        # If there was a previous access and the previous access was the same as this
        # one, don't count it. Instead return the previous count of queries.
        if data is not None and data["last_access_hash"] is not None:
            if data["last_access_hash"] == access_hash:
                return data["queries"]

        query = ("INSERT INTO core.quota (queries, persona_id, qdate, last_access_hash)"
                 " VALUES (%s, %s, %s, %s) ON CONFLICT (persona_id, qdate) DO"
                 " UPDATE SET queries = core.quota.queries + EXCLUDED.queries,"
                 " last_access_hash = EXCLUDED.last_access_hash"
                 " RETURNING core.quota.queries")
        params = (num, persona_id, now_date, access_hash)
        return unwrap(self.query_one(rs, query, params)) or 0

    @overload
    def check_quota(self, rs: RequestState, *, ids: Collection[int]) -> bool: ...

    @overload
    def check_quota(self, rs: RequestState, *, num: int) -> bool: ...

    @overload
    def check_quota(self, rs: RequestState) -> bool: ...

    @internal
    @access("persona")
    def check_quota(self, rs: RequestState, *, ids: Collection[int] = None,
                    num: int = None) -> bool:
        """Check whether the quota was exceeded today.

        Even if quota has been exceeded, never block access to own profile.
        """
        # Validation is done inside.
        if num is None and ids is not None and set(ids) == {rs.user.persona_id}:
            return False
        quota = self.quota(rs, ids=ids, num=num)  # type: ignore
        return (quota > self.conf["QUOTA_VIEWS_PER_DAY"]
                and not {"cde_admin", "core_admin"} & rs.user.roles)

    @access("cde")
    def get_cde_users(self, rs: RequestState, persona_ids: Collection[int]
                      ) -> CdEDBObjectMap:
        """Get an cde view on some data sets."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        with Atomizer(rs):
            if self.check_quota(rs, ids=persona_ids):
                raise QuotaException(n_("Too many queries."))
            ret = self.retrieve_personas(rs, persona_ids, columns=PERSONA_CDE_FIELDS)
            if any(not e['is_cde_realm'] for e in ret.values()):
                raise RuntimeError(n_("Not a CdE user."))
            if (not {"cde_admin", "core_admin"} & rs.user.roles
                    and ("searchable" not in rs.user.roles
                         and any((e['id'] != rs.user.persona_id
                                  and not e['is_searchable'])
                                 for e in ret.values()))):
                raise RuntimeError(n_("Improper access to member data."))
            return ret
    get_cde_user: _GetPersonaProtocol = singularize(
        get_cde_users, "persona_ids", "persona_id")

    @access("ml")
    def get_ml_users(self, rs: RequestState, persona_ids: Collection[int]
                     ) -> CdEDBObjectMap:
        """Get an ml view on some data sets."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        ret = self.retrieve_personas(rs, persona_ids, columns=PERSONA_ML_FIELDS)
        if any(not e['is_ml_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an ml user."))
        return ret
    get_ml_user: _GetPersonaProtocol = singularize(
        get_ml_users, "persona_ids", "persona_id")

    @access("assembly")
    def get_assembly_users(self, rs: RequestState, persona_ids: Collection[int]
                           ) -> CdEDBObjectMap:
        """Get an assembly view on some data sets."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        ret = self.retrieve_personas(rs, persona_ids, columns=PERSONA_ASSEMBLY_FIELDS)
        if any(not e['is_assembly_realm'] for e in ret.values()):
            raise RuntimeError(n_("Not an assembly user."))
        return ret
    get_assembly_user: _GetPersonaProtocol = singularize(
        get_assembly_users, "persona_ids", "persona_id")

    @access("persona")
    def get_total_personas(self, rs: RequestState, persona_ids: Collection[int]
                           ) -> CdEDBObjectMap:
        """Acquire data sets for specified ids.

        This includes all attributes regardless of which realm they
        pertain to.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        if (persona_ids != {rs.user.persona_id} and not self.is_admin(rs)
                and any(not self.is_relative_admin(rs, anid, allow_meta_admin=True)
                        for anid in persona_ids)):
            raise PrivilegeError(n_("Must be privileged."))
        return self.retrieve_personas(rs, persona_ids, columns=PERSONA_ALL_FIELDS)
    get_total_persona: _GetPersonaProtocol = singularize(
        get_total_personas, "persona_ids", "persona_id")

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def create_persona(self, rs: RequestState, data: CdEDBObject,
                       submitted_by: int = None, ignore_warnings: bool = False
                       ) -> DefaultReturnCode:
        """Instantiate a new data set.

        This does the house-keeping and inserts the corresponding entry in
        the changelog.

        :param submitted_by: Allow to override the submitter for genesis.
        :returns: The id of the newly created persona.
        """
        data = affirm(vtypes.Persona, data,
                      creation=True, _ignore_warnings=ignore_warnings)
        submitted_by = affirm_optional(vtypes.ID, submitted_by)
        # zap any admin attempts
        data.update({
            'is_meta_admin': False,
            'is_archived': False,
            'is_assembly_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_core_admin': False,
            'is_event_admin': False,
            'is_ml_admin': False,
            'is_cdelokal_admin': False,
            'is_purged': False,
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
                "code": const.MemberChangeStati.committed,
                "persona_id": new_id,
                "change_note": "Account erstellt.",
            })
            # remove unlogged attributes
            del data['password_hash']
            del data['fulltext']
            self.sql_insert(rs, "core.changelog", data)
            self.core_log(rs, const.CoreLogCodes.persona_creation, new_id)
        return new_id

    @access("anonymous")
    def login(self, rs: RequestState, username: str, password: str,
              ip: str) -> Optional[str]:
        """Create a new session.

        This invalidates all existing sessions for this persona. Sessions
        are bound to an IP-address, for bookkeeping purposes.

        In case of successful login, this updates the request state with a
        new user object and escalates the database connection to reflect the
        non-anonymous access.

        :returns: the session-key for the new session
        """
        username = affirm(vtypes.PrintableASCII, username)
        password = affirm(str, password)
        ip = affirm(vtypes.PrintableASCII, ip)
        # note the lower-casing for email addresses
        query = ("SELECT id, is_meta_admin, is_core_admin FROM core.personas"
                 " WHERE username = lower(%s) AND is_active = True")
        data = self.query_one(rs, query, (username,))
        if not data or (
                not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]
                and not self.verify_persona_password(rs, password, data["id"])):
            # log message to be picked up by fail2ban
            self.logger.warning("CdEDB login failure from {} for {}".format(
                ip, username))
            return None
        if self.conf["LOCKDOWN"] and not (data['is_meta_admin']
                                          or data['is_core_admin']):
            # Short circuit in case of lockdown
            return None
        sessionkey = token_hex()

        with Atomizer(rs):
            # Invalidate expired sessions, but keep other around.
            timestamp = now()
            ctime_cutoff = timestamp - self.conf["SESSION_LIFESPAN"]
            atime_cutoff = timestamp - self.conf["SESSION_TIMEOUT"]
            query = ("UPDATE core.sessions SET is_active = False"
                     " WHERE persona_id = %s AND is_active = True"
                     " AND (ctime < %s OR atime < %s) ")
            self.query_exec(rs, query, (data["id"], ctime_cutoff, atime_cutoff))
            query = ("INSERT INTO core.sessions (persona_id, ip, sessionkey)"
                     " VALUES (%s, %s, %s)")
            self.query_exec(rs, query, (data["id"], ip, sessionkey))

            # Terminate oldest sessions if we are over the allowed limit.
            query = ("SELECT id FROM core.sessions"
                     " WHERE persona_id = %s AND is_active = True"
                     " ORDER BY atime DESC OFFSET %s")
            old_sessions = self.query_all(
                rs, query, (data["id"], self.conf["MAX_ACTIVE_SESSIONS"]))
            if old_sessions:
                query = ("UPDATE core.sessions SET is_active = FALSE"
                         " WHERE id = ANY(%s)")
                self.query_exec(rs, query, ([e["id"] for e in old_sessions],))

        # Escalate db privilege role in case of successful login.
        # This will not be deescalated.
        if rs.conn.is_contaminated:
            raise RuntimeError(n_("Atomized – impossible to escalate."))

        # TODO: This is needed because of an implementation detail of the login in the
        #  frontend. Namely wanting to check consent decision status for cde users.
        #  Maybe rework this somehow.
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
        if data is None:
            raise RuntimeError("Impossible.")
        vals = {k: data[k] for k in (
            'username', 'given_names', 'display_name', 'family_name')}
        vals['persona_id'] = data['id']
        rs.user = User(roles=extract_roles(data), **vals)

        return sessionkey

    @access("persona")
    def logout(self, rs: RequestState, this_session: bool = True,
               other_sessions: bool = False) -> DefaultReturnCode:
        """Invalidate some sessions, depending on the parameters."""
        this_session = affirm(bool, this_session)
        other_sessions = affirm(bool, other_sessions)
        query = "UPDATE core.sessions SET is_active = False, atime = now()"
        constraints = ["persona_id = %s", "is_active = True"]
        params: List[Any] = [rs.user.persona_id]
        if not this_session and not other_sessions:
            return 0
        elif not other_sessions:
            constraints.append("sessionkey = %s")
            params.append(rs.sessionkey)
        elif not this_session:
            constraints.append("sessionkey != %s")
            params.append(rs.sessionkey)
        query += " WHERE " + " AND ".join(constraints)
        return self.query_exec(rs, query, params)

    @access("core_admin")
    def deactivate_old_sessions(self, rs: RequestState) -> DefaultReturnCode:
        """Deactivate old leftover sessions."""
        query = ("UPDATE core.sessions SET is_active = False"
                 " WHERE is_active = True AND atime < now() - INTERVAL '30 days'")
        return self.query_exec(rs, query, ())

    @access("core_admin")
    def clean_session_log(self, rs: RequestState) -> DefaultReturnCode:
        """Delete old entries from the sessionlog."""
        query = ("DELETE FROM core.sessions WHERE is_active = False"
                 " AND atime < now() - INTERVAL '30 days'"
                 " AND (persona_id, atime) NOT IN"
                 " (SELECT persona_id, MAX(atime) AS atime FROM core.sessions"
                 "  WHERE is_active = False GROUP BY persona_id)")

        return self.query_exec(rs, query, ())

    @access("persona")
    def verify_ids(self, rs: RequestState, persona_ids: Collection[int],
                   is_archived: bool = None) -> bool:
        """Check that persona ids do exist.

        :param is_archived: If given, check the given archival status.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        is_archived = affirm_optional(bool, is_archived)
        if persona_ids == {rs.user.persona_id}:
            return True
        query = "SELECT COUNT(*) AS num FROM core.personas"
        constraints: List[str] = ["id = ANY(%s)"]
        params: List[Any] = [persona_ids]
        if is_archived is not None:
            constraints.append("is_archived = %s")
            params.append(is_archived)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)
        num = unwrap(self.query_one(rs, query, params))
        return num == len(persona_ids)

    class _VerifyIDProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int,
                     is_archived: bool = None) -> bool: ...
    verify_id: _VerifyIDProtocol = singularize(
        verify_ids, "persona_ids", "persona_id", passthrough=True)

    @internal
    @access("anonymous")
    def get_roles_multi(self, rs: RequestState, persona_ids: Collection[Optional[int]],
                        introspection_only: bool = False
                        ) -> Dict[Optional[int], Set[Role]]:
        """Resolve ids into roles.

        Returns an empty role set for inactive users."""
        if set(persona_ids) == {rs.user.persona_id}:
            return {rs.user.persona_id: rs.user.roles}
        bits = PERSONA_STATUS_FIELDS + ("id",)
        data = self.sql_select(rs, "core.personas", bits, persona_ids)
        return {d['id']: extract_roles(d, introspection_only) for d in data}

    class _GetRolesSingleProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: Optional[int],
                     introspection_only: bool = False) -> Set[Role]: ...
    get_roles_single: _GetRolesSingleProtocol = singularize(get_roles_multi)

    @access("persona")
    def get_realms_multi(self, rs: RequestState, persona_ids: Collection[int],
                         introspection_only: bool = False
                         ) -> Dict[Optional[int], Set[Realm]]:
        """Resolve persona ids into realms (only for active users)."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        roles = self.get_roles_multi(rs, persona_ids, introspection_only)
        all_realms = {"cde", "event", "assembly", "ml"}
        return {key: value & all_realms for key, value in roles.items()}

    class _GetRealmsSingleProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int,
                     introspection_only: bool = False) -> Set[Realm]: ...
    get_realms_single: _GetRealmsSingleProtocol = singularize(
        get_realms_multi, "persona_ids", "persona_id")

    @access("persona")
    def verify_personas(self, rs: RequestState, persona_ids: Collection[int],
                        required_roles: Collection[Role] = None,
                        introspection_only: bool = True) -> bool:
        """Check whether certain ids map to actual (active) personas.

        Note that this will return True for an empty set of ids.

        :param required_roles: If given check that all personas have
          these roles.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        required_roles = required_roles or tuple()
        required_roles = affirm_set(str, required_roles)
        roles = self.get_roles_multi(rs, persona_ids, introspection_only)
        return len(roles) == len(persona_ids) and all(
            value >= required_roles for value in roles.values())

    class _VerifyPersonaProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int,
                     required_roles: Collection[Role] = None,
                     introspection_only: bool = True) -> bool: ...
    verify_persona: _VerifyPersonaProtocol = singularize(
        verify_personas, "persona_ids", "persona_id", passthrough=True)

    @access("anonymous")
    def genesis_set_attachment(self, rs: RequestState, attachment: bytes
                               ) -> str:
        """Store a file for genesis usage. Returns the file hash."""
        attachment = affirm(vtypes.PDFFile, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.genesis_attachment_dir / myhash
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(attachment)
        return myhash

    @access("anonymous")
    def genesis_check_attachment(self, rs: RequestState, attachment_hash: str
                                 ) -> bool:
        """Check whether a genesis attachment with the given hash is available.

        Contrary to `genesis_get_attachment` this does not retrieve it's
        content.
        """
        attachment_hash = affirm(str, attachment_hash)
        path = self.genesis_attachment_dir / attachment_hash
        return path.is_file()

    @access("core_admin", "cde_admin", "event_admin", "ml_admin",
            "assembly_admin")
    def genesis_get_attachment(self, rs: RequestState, attachment_hash: str
                               ) -> Optional[bytes]:
        """Retrieve a stored genesis attachment."""
        attachment_hash = affirm(str, attachment_hash)
        path = self.genesis_attachment_dir / attachment_hash
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    @internal
    @access("core_admin")
    def genesis_attachment_usage(self, rs: RequestState,
                                 attachment_hash: str) -> bool:
        """Check whether a genesis attachment is still referenced in a case."""
        attachment_hash = affirm(str, attachment_hash)
        query = "SELECT COUNT(*) FROM core.genesis_cases WHERE attachment = %s"
        return bool(unwrap(self.query_one(rs, query, (attachment_hash,))))

    @access("core_admin")
    def genesis_forget_attachments(self, rs: RequestState) -> int:
        """Delete genesis attachments that are no longer in use."""
        ret = 0
        for f in self.genesis_attachment_dir.iterdir():
            if f.is_file() and not self.genesis_attachment_usage(rs, str(f)):
                f.unlink()
                ret += 1
        return ret

    @access("anonymous")
    def verify_existence(self, rs: RequestState, email: str) -> bool:
        """Check wether a certain email belongs to any persona."""
        email = affirm(vtypes.Email, email)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE username = %s"
        num1 = unwrap(self.query_one(rs, query, (email,))) or 0
        query = glue("SELECT COUNT(*) AS num FROM core.genesis_cases",
                     "WHERE username = %s AND case_status = ANY(%s)")
        # This should be all stati which are not final.
        stati = (const.GenesisStati.unconfirmed,
                 const.GenesisStati.to_review,
                 const.GenesisStati.approved)  # approved is a temporary state.
        num2 = unwrap(self.query_one(rs, query, (email, stati))) or 0
        return bool(num1 + num2)

    RESET_COOKIE_PAYLOAD = "X"

    def _generate_reset_cookie(
            self, rs: RequestState, persona_id: int, salt: str,
            timeout: datetime.timedelta = datetime.timedelta(seconds=60)
    ) -> str:
        """Create a cookie which authorizes a specific reset action.

        The cookie depends on the inputs as well as a server side secret.
        """
        with Atomizer(rs):
            if not self.is_admin(rs) and "meta_admin" not in rs.user.roles:
                roles = self.get_roles_single(rs, persona_id)
                if any("admin" in role for role in roles):
                    raise PrivilegeError(n_("Preventing reset of admin."))
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            if password_hash is None:
                # A personas password hash cannot be empty.
                raise ValueError(n_("Persona does not exist."))
            # This defines a specific account/password combination as purpose
            cookie = encode_parameter(
                salt, str(persona_id), password_hash,
                self.RESET_COOKIE_PAYLOAD, persona_id=None, timeout=timeout)
            return cookie

    # # This should work but Literal seems to be broken.
    # # https://github.com/python/mypy/issues/7399
    # if TYPE_CHECKING:
    #     from typing_extensions import Literal
    #     ret_type = Union[Tuple[Literal[False], str],
    #                      Tuple[Literal[True], None]]
    # else:
    #     ret_type = Tuple[bool, Optional[str]]
    ret_type = Tuple[bool, Optional[str]]

    def _verify_reset_cookie(self, rs: RequestState, persona_id: int, salt: str,
                             cookie: str) -> ret_type:
        """Check a provided cookie for correctness.

        :returns: The bool signals success, the str is an error message or
            None if successful.
        """
        with Atomizer(rs):
            password_hash = unwrap(self.sql_select_one(
                rs, "core.personas", ("password_hash",), persona_id))
            if password_hash is None:
                # A personas password hash cannot be empty.
                raise ValueError(n_("Persona does not exist."))
            timeout, msg = decode_parameter(
                salt, str(persona_id), password_hash, cookie, persona_id=None)
            if msg is None:
                if timeout:
                    return False, n_("Link expired.")
                else:
                    return False, n_("Link invalid or already used.")
            if msg != self.RESET_COOKIE_PAYLOAD:
                return False, n_("Link invalid or already used.")
            return True, None

    def modify_password(self, rs: RequestState, new_password: str,
                        old_password: str = None, reset_cookie: str = None,
                        persona_id: int = None) -> Tuple[bool, str]:
        """Helper for manipulating password entries.

        The persona_id parameter is only for the password reset case. We
        intentionally only allow to change the own password.

        An authorization must be provided, either by ``old_password`` or
        ``reset_cookie``.

        This escalates database connection privileges in the case of a
        password reset (which is by its nature anonymous).

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
            if not self.verify_persona_password(rs, old_password, persona_id):
                return False, n_("Password verification failed.")
        if reset_cookie:
            success, msg = self.verify_reset_cookie(
                rs, persona_id, reset_cookie)
            if not success:
                return False, msg  # type: ignore
        if not new_password:
            return False, n_("No new password provided.")
        if not validate_is(vtypes.PasswordStrength, new_password):
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
    def change_password(self, rs: RequestState, old_password: str,
                        new_password: str) -> Tuple[bool, str]:
        """
        :type rs: :py:class:`cdedb.common.RequestState`
        :type old_password: str
        :type new_password: str
        :rtype: (bool, str)
        :returns: see :py:meth:`modify_password`
        """
        old_password = affirm(str, old_password)
        new_password = affirm(str, new_password)
        with Atomizer(rs):
            ret = self.modify_password(rs, new_password, old_password=old_password)
            self.core_log(rs, const.CoreLogCodes.password_change,
                          rs.user.persona_id)
        return ret

    @access("anonymous")
    def check_password_strength(
        self, rs: RequestState, password: str, *,
        email: str = None, persona_id: int = None, argname: str = None
    ) -> Tuple[Optional[vtypes.PasswordStrength], List[Error]]:
        """Check the password strength using some additional userdate.

        This escalates database connection privileges in the case of an
        anonymous request, that is for a password reset.
        """
        password = affirm(str, password)
        email = affirm_optional(str, email)
        persona_id = affirm_optional(vtypes.ID, persona_id)
        argname = affirm_optional(str, argname)

        if email is None and persona_id is None:
            raise ValueError(n_("No input provided."))
        elif email and persona_id:
            raise ValueError(n_("More than one input provided."))
        if email:
            persona_id = unwrap(self.sql_select_one(
                rs, "core.personas", ("id",), email, entity_key="username"))

        columns_of_interest = [
            "is_cde_realm", "is_meta_admin", "is_core_admin", "is_cde_admin",
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
            if persona is None:
                raise ValueError(n_("Persona does not exist."))
        finally:
            # deescalate
            if orig_conn:
                rs.conn = orig_conn

        admin = any(persona[admin] for admin in
                    ("is_meta_admin", "is_core_admin", "is_cde_admin",
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

        password, errs = validate_check(vtypes.PasswordStrength, password,
                                        argname=argname, admin=admin, inputs=inputs)

        return password, errs

    @access("anonymous")
    def make_reset_cookie(self, rs: RequestState, email: str,
                          timeout: datetime.timedelta = datetime.timedelta(
                              seconds=60)) -> Tuple[bool, str]:
        """Perform preparation for a recovery.

        This generates a reset cookie which can be used in a second step
        to actually reset the password. To reset the password for a
        privileged account you need to have privileges yourself.

        :returns: The ``bool`` indicates success and the ``str`` is
          either the reset cookie or an error message.
        """
        timeout = timeout or self.conf["PARAMETER_TIMEOUT"]
        email = affirm(vtypes.Email, email)
        data = self.sql_select_one(rs, "core.personas", ("id", "is_active"),
                                   email, entity_key="username")
        if not data:
            return False, n_("Nonexistent user.")
        if not data['is_active']:
            return False, n_("Inactive user.")
        with Atomizer(rs):
            ret = self.generate_reset_cookie(rs, data['id'], timeout=timeout)
            self.core_log(rs, const.CoreLogCodes.password_reset_cookie, data['id'])
        return True, ret

    @access("anonymous")
    def reset_password(self, rs: RequestState, email: str, new_password: str,
                       cookie: str) -> Tuple[bool, str]:
        """Perform a recovery.

        Authorization is guaranteed by the cookie.

        :returns: see :py:meth:`modify_password`
        """
        email = affirm(vtypes.Email, email)
        new_password = affirm(str, new_password)
        cookie = affirm(str, cookie)
        data = self.sql_select_one(rs, "core.personas", ("id",), email,
                                   entity_key="username")
        if not data:
            return False, n_("Nonexistent user.")
        if self.conf["LOCKDOWN"]:
            return False, n_("Lockdown active.")
        persona_id = unwrap(data)
        success, msg = self.modify_password(
            rs, new_password, reset_cookie=cookie, persona_id=persona_id)
        if success:
            # Since they should usually be called inside an atomized context, logs
            # demand an Atomizer by default. However, due to privilege escalation inside
            # modify_password, this does not work and relax that claim.
            self.core_log(rs, const.CoreLogCodes.password_reset, persona_id,
                          atomized=False)
        return success, msg

    @access("anonymous")
    def genesis_request(self, rs: RequestState, data: CdEDBObject,
                        ignore_warnings: bool = False
                        ) -> Optional[DefaultReturnCode]:
        """Log a request for a new account.

        This is the initial entry point for such a request.

        :param ignore_warnings: Ignore errors with kind ValidationWarning
        :returns: id of the new request or None if the username is already
          taken
        """
        data = affirm(vtypes.GenesisCase, data,
                      creation=True, _ignore_warnings=ignore_warnings)

        if self.verify_existence(rs, data['username']):
            return None
        if self.conf["LOCKDOWN"] and not self.is_admin(rs):
            return None
        data['case_status'] = const.GenesisStati.unconfirmed
        with Atomizer(rs):
            ret = self.sql_insert(rs, "core.genesis_cases", data)
            self.core_log(rs, const.CoreLogCodes.genesis_request, persona_id=None,
                          change_note=data['username'])
        return ret

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def delete_genesis_case_blockers(self, rs: RequestState,
                                     case_id: int) -> DeletionBlockers:
        """Determine what keeps a genesis case from being deleted.

        Possible blockers:

        * unconfirmed: A genesis case with status unconfirmed may only be
                       deleted after the timeout period has passed.
        * case_status: A genesis case may not be deleted if it has one of the
                       following stati: to_review, approved.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """

        case_id = affirm(vtypes.ID, case_id)
        blockers: DeletionBlockers = {}

        case = self.genesis_get_case(rs, case_id)
        if (case["case_status"] == const.GenesisStati.unconfirmed and
                now() < case["ctime"] + self.conf["PARAMETER_TIMEOUT"]):
            blockers["unconfirmed"] = [case_id]
        if case["case_status"] in {const.GenesisStati.to_review,
                                   const.GenesisStati.approved}:
            blockers["case_status"] = [case["case_status"]]

        return blockers

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def delete_genesis_case(self, rs: RequestState, case_id: int,
                            cascade: Collection[str] = None
                            ) -> DefaultReturnCode:
        """Remove a genesis case."""

        case_id = affirm(vtypes.ID, case_id)
        blockers = self.delete_genesis_case_blockers(rs, case_id)
        if "unconfirmed" in blockers.keys():
            raise ValueError(n_("Unable to remove unconfirmed genesis case "
                                "before confirmation timeout."))
        if "case_status" in blockers.keys():
            raise ValueError(n_("Unable to remove genesis case with status {}.")
                             .format(blockers["case_status"]))
        if not cascade:
            cascade = set()
        cascade = affirm_set(str, cascade) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "genesis case",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            case = self.genesis_get_case(rs, case_id)
            if cascade:
                if "unconfirmed" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "unconfirmed"})
                if "case_status" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "case_status"})

            if not blockers:
                ret *= self.sql_delete_one(rs, "core.genesis_cases", case_id)
                self.core_log(rs, const.CoreLogCodes.genesis_deleted,
                              persona_id=None, change_note=case["username"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})

        return ret

    @access("anonymous")
    def genesis_case_by_email(self, rs: RequestState,
                              email: str) -> Optional[int]:
        """Get the id of an unconfirmed genesis case for a given email.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type email: str
        :rtype: int or None
        :returns: The case id or None if no such case exists.
        """
        email = affirm(str, email)
        query = glue("SELECT id FROM core.genesis_cases",
                     "WHERE username = %s AND case_status = %s")
        params = (email, const.GenesisStati.unconfirmed)
        data = self.query_one(rs, query, params)
        return unwrap(data) if data else None

    @access("anonymous")
    def genesis_verify(self, rs: RequestState, case_id: int) -> Tuple[int, str]:
        """Confirm the new email address and proceed to the next stage.

        Returning the realm is a conflation caused by lazyness, but before
        we create another function bloating the code this will do.

        :returns: (default return code, realm of the case if successful)
            A negative return code means, that the case was already verified.
            A zero return code means the case was not found or another error
            occured.
        """
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            data = self.sql_select_one(
                rs, "core.genesis_cases", ("realm", "username", "case_status"),
                case_id)
            # These should be displayed as useful errors in the frontend.
            if not data:
                return 0, "core"
            elif not data["case_status"] == const.GenesisStati.unconfirmed:
                return -1, data["realm"]
            query = glue("UPDATE core.genesis_cases SET case_status = %s",
                         "WHERE id = %s AND case_status = %s")
            params = (const.GenesisStati.to_review, case_id,
                      const.GenesisStati.unconfirmed)
            ret = self.query_exec(rs, query, params)
            if ret:
                self.core_log(
                    rs, const.CoreLogCodes.genesis_verified, persona_id=None,
                    change_note=data["username"])
            return ret, data["realm"]

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis_list_cases(self, rs: RequestState,
                           stati: Collection[const.GenesisStati] = None,
                           realms: Collection[str] = None) -> CdEDBObjectMap:
        """List persona creation cases.

        Restrict to certain stati and certain target realms.
        """
        realms = realms or []
        realms = affirm_set(str, realms)
        stati = stati or set()
        stati = affirm_set(const.GenesisStati, stati)
        if not realms and "core_admin" not in rs.user.roles:
            raise PrivilegeError(n_("Not privileged."))
        elif not all({"{}_admin".format(realm), "core_admin"} & rs.user.roles
                     for realm in realms):
            raise PrivilegeError(n_("Not privileged."))
        query = ("SELECT id, ctime, username, given_names, family_name,"
                 " case_status FROM core.genesis_cases")
        conditions = []
        params: List[Any] = []
        if realms:
            conditions.append("realm = ANY(%s)")
            params.append(realms)
        if stati:
            conditions.append("case_status = ANY(%s)")
            params.append(stati)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis_get_cases(self, rs: RequestState, genesis_case_ids: Collection[int]
                          ) -> CdEDBObjectMap:
        """Retrieve datasets for persona creation cases."""
        genesis_case_ids = affirm_set(vtypes.ID, genesis_case_ids)
        data = self.sql_select(rs, "core.genesis_cases", GENESIS_CASE_FIELDS,
                               genesis_case_ids)
        if ("core_admin" not in rs.user.roles
                and any("{}_admin".format(e['realm']) not in rs.user.roles
                        for e in data)):
            raise PrivilegeError(n_("Not privileged."))
        return {e['id']: e for e in data}

    class _GenesisGetCaseProtocol(Protocol):
        def __call__(self, rs: RequestState, genesis_case_id: int) -> CdEDBObject: ...
    genesis_get_case: _GenesisGetCaseProtocol = singularize(
        genesis_get_cases, "genesis_case_ids", "genesis_case_id")

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis_modify_case(self, rs: RequestState, data: CdEDBObject,
                            ignore_warnings: bool = False) -> DefaultReturnCode:
        """Modify a persona creation case.

        :param ignore_warnings: Ignore errors with kind ValidationWarning
        """
        data = affirm(vtypes.GenesisCase, data,
                      _ignore_warnings=ignore_warnings)

        with Atomizer(rs):
            current = self.sql_select_one(
                rs, "core.genesis_cases", ("case_status", "username", "realm"),
                data['id'])
            if current is None:
                raise ValueError(n_("Genesis case does not exist."))
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
                        change_note=current['username'])
                elif data['case_status'] == const.GenesisStati.rejected:
                    self.core_log(
                        rs, const.CoreLogCodes.genesis_rejected, persona_id=None,
                        change_note=current['username'])
        return ret

    @access("core_admin", "cde_admin", "event_admin", "assembly_admin",
            "ml_admin")
    def genesis(self, rs: RequestState, case_id: int) -> DefaultReturnCode:
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account.
        """
        case_id = affirm(vtypes.ID, case_id)
        with Atomizer(rs):
            case = unwrap(self.genesis_get_cases(rs, (case_id,)))
            data = {k: v for k, v in case.items()
                    if k in PERSONA_ALL_FIELDS and k != "id"}
            data['display_name'] = data['given_names']
            merge_dicts(data, PERSONA_DEFAULTS)
            # Fix realms, so that the persona validator does the correct thing
            data.update(GENESIS_REALM_OVERRIDE[case['realm']])
            data = affirm(vtypes.Persona, data,
                          creation=True, _ignore_warnings=True)
            if case['case_status'] != const.GenesisStati.approved:
                raise ValueError(n_("Invalid genesis state."))
            roles = extract_roles(data)
            if extract_realms(roles) != \
                    ({case['realm']} | implied_realms(case['realm'])):
                raise PrivilegeError(n_("Wrong target realm."))
            ret = self.create_persona(
                rs, data, submitted_by=case['reviewer'], ignore_warnings=True)
            update = {
                'id': case_id,
                'case_status': const.GenesisStati.successful,
            }
            self.sql_update(rs, "core.genesis_cases", update)
            return ret

    @access("core_admin")
    def find_doppelgangers(self, rs: RequestState,
                           persona: CdEDBObject) -> CdEDBObjectMap:
        """Look for accounts with data similar to the passed dataset.

        This is for batch admission, where we may encounter datasets to
        already existing accounts. In that case we do not want to create
        a new account.

        :returns: A dict of possibly matching account data.
        """
        persona = affirm(vtypes.Persona, persona)
        scores: Dict[int, int] = collections.defaultdict(lambda: 0)
        queries: List[Tuple[int, str, Tuple[Any, ...]]] = [
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
            (21, "username = %s", (persona['username'],)),
        ]
        # Omit queries where some parameters are None
        queries = tuple(e for e in queries if all(x is not None for x in e[2]))
        for score, condition, params in queries:
            query = f"SELECT id FROM core.personas WHERE {condition}"
            result = self.query_all(rs, query, params)
            for e in result:
                scores[unwrap(e)] += score
        cutoff = 21
        max_entries = 7
        persona_ids = tuple(k for k, v in scores.items() if v > cutoff)
        persona_ids = xsorted(persona_ids, key=lambda k: -scores.get(k, 0))
        persona_ids = persona_ids[:max_entries]
        return self.get_total_personas(rs, persona_ids)

    @access("anonymous")
    def get_meta_info(self, rs: RequestState) -> CdEDBObject:
        """Retrieve changing info about the DB and the CdE e.V.

        This is a relatively painless way to specify lots of constants
        like who is responsible for donation certificates.
        """
        query = "SELECT info FROM core.meta_info LIMIT 1"
        return cast(CdEDBObject, unwrap(self.query_one(rs, query, tuple())))

    @access("core_admin")
    def set_meta_info(self, rs: RequestState,
                      data: CdEDBObject) -> DefaultReturnCode:
        """Change infos about the DB and the CdE e.V.

        This is expected to occur regularly.
        """
        with Atomizer(rs):
            meta_info = self.get_meta_info(rs)
            # Late validation since we need to know the keys
            data = affirm(vtypes.MetaInfo, data, keys=meta_info.keys())
            meta_info.update(data)
            query = "UPDATE core.meta_info SET info = %s"
            return self.query_exec(rs, query, (PsycoJson(meta_info),))

    @access("core_admin")
    def get_cron_store(self, rs: RequestState, name: str) -> CdEDBObject:
        """Retrieve the persistent store of a cron job.

        If no entry exists, an empty dict ist returned.
        """
        ret = self.sql_select_one(rs, "core.cron_store", ("store",),
                                  name, entity_key="title")
        return unwrap(ret) or {}

    @access("core_admin")
    def set_cron_store(self, rs: RequestState, name: str,
                       data: CdEDBObject) -> DefaultReturnCode:
        """Update the store of a cron job."""
        update = {
            'title': name,
            'store': PsycoJson(data),
        }
        with Atomizer(rs):
            ret = self.sql_update(rs, "core.cron_store", update,
                                  entity_key='title')
            if not ret:
                ret = self.sql_insert(rs, "core.cron_store", update)
            return ret

    def _submit_general_query(self, rs: RequestState,
                              query: Query) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.
        """
        query = affirm(Query, query)
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
    submit_general_query = access("core_admin")(_submit_general_query)

    @access("persona")
    def submit_select_persona_query(self, rs: RequestState,
                                    query: Query) -> Tuple[CdEDBObject, ...]:
        """Accessible version of :py:meth:`submit_general_query`.

        This should be used solely by the persona select API which is also
        accessed by less privileged accounts. The frontend takes the
        necessary precautions.
        """
        query = affirm(Query, query)
        return self._submit_general_query(rs, query)

    @access("droid_resolve")
    def submit_resolve_api_query(self, rs: RequestState,
                                 query: Query) -> Tuple[CdEDBObject, ...]:
        """Accessible version of :py:meth:`submit_general_query`.

        This should be used solely by the resolve API. The frontend takes
        the necessary precautions.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm(Query, query)
        return self.general_query(rs, query)
