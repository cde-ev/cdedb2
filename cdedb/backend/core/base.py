#!/usr/bin/env python3

"""
The `CoreBaseBackend` provides backend functionality related to general user management.

There are several subclasses in separate files which provide additional functionality
related to more specific aspects or user management.

All parts are combined together in the `CoreBackend` class via multiple inheritance,
together with a handful of high-level methods, that use functionalities of multiple
backend parts.
"""
import collections
import copy
import datetime
import decimal
from collections.abc import Collection
from secrets import token_hex
from typing import Any, Optional, Protocol, Union, overload

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
import cdedb.models.core as models
from cdedb.backend.common import (
    AbstractBackend,
    access,
    affirm_array_validation as affirm_array,
    affirm_dataclass,
    affirm_set_validation as affirm_set,
    affirm_validation as affirm,
    affirm_validation_optional as affirm_optional,
    encrypt_password,
    inspect_validation as inspect,
    internal,
    singularize,
    verify_password,
)
from cdedb.common import (
    CdEDBLog,
    CdEDBObject,
    CdEDBObjectMap,
    DefaultReturnCode,
    Error,
    PsycoJson,
    RequestState,
    Role,
    User,
    decode_parameter,
    encode_parameter,
    get_hash,
    glue,
    now,
    unwrap,
)
from cdedb.common.attachment import AttachmentStore
from cdedb.common.exceptions import ArchiveError, PrivilegeError, QuotaException
from cdedb.common.fields import (
    META_INFO_FIELDS,
    PERSONA_ALL_FIELDS,
    PERSONA_ASSEMBLY_FIELDS,
    PERSONA_CDE_FIELDS,
    PERSONA_CORE_FIELDS,
    PERSONA_EVENT_FIELDS,
    PERSONA_ML_FIELDS,
    PERSONA_STATUS_FIELDS,
    PRIVILEGE_CHANGE_FIELDS,
    REALM_SPECIFIC_GENESIS_FIELDS,
)
from cdedb.common.n_ import n_
from cdedb.common.query import Query, QueryOperators, QueryScope
from cdedb.common.query.log_filter import (
    ALL_LOG_FILTERS,
    ChangelogLogFilter,
    CoreLogFilter,
)
from cdedb.common.roles import (
    ADMIN_KEYS,
    ALL_ROLES,
    REALM_ADMINS,
    extract_roles,
    implying_realms,
    privilege_tier,
)
from cdedb.common.sorting import xsorted
from cdedb.config import SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import Atomizer, connection_pool_factory
from cdedb.models.core import EmailAddressReport


class CoreBaseBackend(AbstractBackend):
    """Access to this is probably necessary from everywhere, so we need
    ``@internal`` quite often. """
    realm = "core"

    def __init__(self) -> None:
        super().__init__()
        secrets = SecretsConfig()
        self.connpool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], DATABASE_ROLES,
            secrets, self.conf["DB_HOST"], self.conf["DB_PORT"])
        # local variable to prevent closure over secrets
        reset_salt = secrets["RESET_SALT"]
        self.generate_reset_cookie = (
            lambda rs, persona_id, timeout: self._generate_reset_cookie(
                rs, persona_id, reset_salt, timeout=timeout))
        self.verify_reset_cookie = (
            lambda rs, persona_id, cookie: self._verify_reset_cookie(
                rs, persona_id, reset_salt, cookie))
        self._foto_store = AttachmentStore(self.conf['STORAGE_DIR'] / 'foto',
                                           vtypes.ProfilePicture)
        self._genesis_attachment_store = AttachmentStore(
            self.conf['STORAGE_DIR'] / 'genesis_attachment')

    @access("cde")
    def get_foto_store(self, rs: RequestState) -> AttachmentStore:
        return self._foto_store

    @access("anonymous")
    def get_genesis_attachment_store(self, rs: RequestState) -> AttachmentStore:
        return self._genesis_attachment_store

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
        # Shortcuts to avoid having to retrieve the persona in easy cases.
        if self.is_admin(rs):
            return True
        if allow_meta_admin and "meta_admin" in rs.user.roles:
            return True
        persona = self.get_persona(rs, persona_id)
        return self._is_relative_admin(rs, persona)

    @staticmethod
    @internal
    def _is_relative_admin(rs: RequestState, persona: CdEDBObject) -> bool:
        """Internal helper to check relative admin privileges if the persona is already
        available.

        Apart from meta admins, the only difference to `is_relative_admin` is that
        this accepts a full persona, rather than a persona id.
        """
        roles = extract_roles(persona, introspection_only=True)
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

    verify_password = staticmethod(verify_password)
    encrypt_password = staticmethod(encrypt_password)

    @staticmethod
    def create_fulltext(persona: CdEDBObject) -> str:
        """Helper to mangle all data into a single string.

        :param persona: one persona data set to convert into a string for
          fulltext search
        """
        attributes = [
            "title", "username", "display_name", "given_names", "family_name",
            "birth_name", "name_supplement", "birthday", "telephone", "mobile",
            "postal_code", "location", "postal_code2", "location2", "weblink",
            "specialisation", "affiliation", "timeline", "interests", "free_form"]
        if persona["show_address"]:
            attributes += ("address_supplement", "address")
        if persona["show_address2"]:
            attributes += ("address_supplement2", "address2")
        values = (str(persona[a]) for a in attributes if persona[a] is not None)
        return " ".join(values)

    def core_log(self, rs: RequestState, code: const.CoreLogCodes,
                 persona_id: Optional[int] = None, change_note: Optional[str] = None,
                 atomized: bool = True, suppress_persona_id: bool = False,
                 ) -> DefaultReturnCode:
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
        params = (
            code, rs.user.persona_id if not suppress_persona_id else None, persona_id,
            change_note,
        )
        return self.query_exec(rs, query, params)

    @access("persona")
    def log_quota_violation(self, rs: RequestState) -> DefaultReturnCode:
        """Log a quota violation.

        Since a quota violation raises an exception which is only handled at application
        level, this can not be done in an Atomizer with the violating action. This leads
        to the effect that every time a user tries to violate their quota, a log entry
        is added.
        """
        return self.core_log(rs, const.CoreLogCodes.quota_violation, rs.user.persona_id,
                             atomized=False)

    @access("persona")
    def log_contact_reply(self, rs: RequestState, recipient: str) -> DefaultReturnCode:
        """Log who sent a reply to an anonymous message originally sent to whom."""
        recipient = affirm(vtypes.Email, recipient)
        return self.core_log(rs, const.CoreLogCodes.reply_to_anonymous_message,
                             change_note=recipient, atomized=False)

    @internal
    @access("cde")
    def finance_log(self, rs: RequestState, code: const.FinanceLogCodes,
                    persona_id: Optional[int], delta: Optional[decimal.Decimal],
                    new_balance: Optional[decimal.Decimal],
                    change_note: Optional[str] = None,
                    transaction_date: Optional[datetime.date] = None,
                    ) -> DefaultReturnCode:
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
            "change_note": change_note,
            "transaction_date": transaction_date,
        }
        with Atomizer(rs):
            query = """
                SELECT COUNT(*) AS members, COALESCE(SUM(balance), 0) AS member_total
                FROM core.personas
                WHERE is_member = True
            """
            tmp = self.query_one(rs, query, tuple())
            if tmp:
                data.update(tmp)
            else:
                self.logger.error(f"Could not determine member count and total"
                                  f" member balance for creating log entry {data!r}.")
                data.update(members=0, total=0)
            query = """
                SELECT COALESCE(SUM(balance), 0) AS total
                FROM core.personas
            """
            tmp = self.query_one(rs, query, ())
            if tmp:
                data.update(tmp)
            else:
                self.logger.error(f"Could not determine total balance for creating"
                                  f" log entry {data!r}.")
            return self.sql_insert(rs, "cde.finance_log", data)

    @access(*REALM_ADMINS)
    def redact_log(self, rs: RequestState, log_table: str, log_id: int,
                   change_note: Optional[str] = None) -> DefaultReturnCode:
        """Redacts log messages.

        We usually do not want to use this, but keep it as a measure to redact
        privacy-sensitive information or deragoratory statements.
        Access validation for this is rather lax, there shall be no frontend endpoints
        to access this freely."""
        log_table = affirm(str, log_table)
        log_id = affirm(int, log_id)
        change_note = affirm_optional(str, change_note)

        if log_table not in {log_filter.log_table for log_filter in ALL_LOG_FILTERS}:
            raise ValueError("Unknown log")

        update = {
            "id": log_id,
            "change_note": change_note,
        }
        self.logger.warning(
            f"Redacted log message for entry with id {log_id} in {log_table}.")
        return self.sql_update(rs, log_table, update)

    @access("core_admin", "auditor")
    def retrieve_log(self, rs: RequestState, log_filter: CoreLogFilter) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(CoreLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @access("core_admin", "auditor")
    def retrieve_changelog_meta(self, rs: RequestState, log_filter: ChangelogLogFilter,
                                ) -> CdEDBLog:
        """Get changelog activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        log_filter = affirm_dataclass(ChangelogLogFilter, log_filter)
        return self.generic_retrieve_log(rs, log_filter)

    @staticmethod
    @internal
    def _get_changelog_inconsistencies(
            persona: CdEDBObject, generation: CdEDBObject) -> list[str]:
        """Helper to get actual inconsistencies between changelog and core.personas.

        This is outlined to avoid duplicated calls to changelog_get_history and
        get_total_persona in changelog_submit_change.

        :returns: A list of inconsistent field names.
        """
        if generation['code'] != const.PersonaChangeStati.committed:
            raise RuntimeError(n_("Given changelog generation must be committed."))
        return [key for key in persona if persona[key] != generation[key]]

    @access("persona")
    def get_changelog_inconsistencies(self, rs: RequestState,
                                      persona_id: int) -> Optional[list[str]]:
        """Get inconsistencies between latest committed changelog entry and
        core.personas.

        If None is returned, there was no committed state in the changelog (which is
        an error by itself).
        If an empty list is returned, changelog and core.personas are consistent.

        :returns: A list of inconsistent field names, an empty list or None.
        """
        with Atomizer(rs):
            committed_generation = self.changelog_get_generation(
                rs, persona_id, committed_only=True)
            committed_state = unwrap(self.changelog_get_history(
                rs, persona_id, generations=(committed_generation,)))
            if not committed_state:
                return None
            persona = self.get_total_persona(rs, persona_id)
        return self._get_changelog_inconsistencies(persona, committed_state)

    def changelog_submit_change(self, rs: RequestState, data: CdEDBObject,
                                generation: Optional[int], may_wait: bool,
                                change_note: str, force_review: bool = False,
                                automated_change: bool = False,
                                ) -> DefaultReturnCode:
        """Insert an entry in the changelog.

        This is an internal helper, that takes care of all the small
        details with regard to e.g. possibly pending changes. If a
        change requires review it has to be committed using
        :py:meth:`changelog_resolve_change` by an administrator.

        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :param may_wait: Whether this change may wait in the changelog. If
          this is ``False`` and there is a pending change in the changelog,
          the new change is slipped in between.
        :param change_note: Comment to record in the changelog entry.
        :param force_review: force a change to be reviewed, even if it may be committed
          without.
        :returns: number of changed entries, however if changes were only
          written to changelog and are waiting for review, the negative number
          of changes written to changelog is returned
        """
        with Atomizer(rs):
            # check for race
            current_generation = self.changelog_get_generation(rs, data['id'])
            if generation is not None and current_generation != generation:
                self.logger.info(f"Generation mismatch ({current_generation} !="
                                 f" {generation}) for {data['id']}")
                return 0

            # The following tries to summarize the logic of this function to
            # facilitate better understanding
            #
            # - if a pending change exists (current_state != committed_state)
            #     - if we may not wait
            #       => stash pending change in `diff`
            #          (current_state == committed_state as if no pending change)
            # - if no actual change (data == current_state)
            #     - if stashed pending change: reenable
            #     - if unstashed pending change exists and is admin:
            #          an admin tried to submit identical change => resolve it
            #     - return
            # - determine review requirements
            # - supersede potential pending changes
            # - insert new changelog entry
            # - if not requiring review: resolve
            # - if stashed pending change: reinstate
            #      (this can only happen if the resolve action was taken)

            # latest state of the changelog which is either committed or pending
            current_state = unwrap(self.changelog_get_history(
                rs, data['id'], generations=(current_generation, )))
            # latest state of the changelog which is committed
            committed_generation = self.changelog_get_generation(
                rs, data['id'], committed_only=True)
            committed_state = unwrap(self.changelog_get_history(
                rs, data['id'], generations=(committed_generation, )))
            # state of the persona in core.personas
            persona = self.get_total_persona(rs, data['id'])

            # Die when committed_state and core.personas are inconsistent.
            if not committed_state:
                raise RuntimeError(n_("No committed state found."))
            if self._get_changelog_inconsistencies(persona, committed_state):
                raise RuntimeError(n_("Persona and Changelog are inconsistent."))

            # handle pending changes
            diff = None
            if current_state['code'] == const.PersonaChangeStati.pending:
                # stash pending change if we may not wait
                if not may_wait:
                    diff = {key: current_state[key] for key in persona
                            if persona[key] != current_state[key]}
                    current_state.update(persona)
                    query = glue("UPDATE core.changelog SET code = %s",
                                 "WHERE persona_id = %s AND code = %s")
                    self.query_exec(rs, query, (
                        const.PersonaChangeStati.displaced, data['id'],
                        const.PersonaChangeStati.pending))

            # determine if something changed
            newly_changed_fields = {key for key, value in data.items()
                                    if value != current_state[key]}
            if not newly_changed_fields:
                if diff:
                    # reenable old change if we were going to displace it
                    query = glue("UPDATE core.changelog SET code = %s",
                                 "WHERE persona_id = %s AND generation = %s")
                    self.query_exec(rs, query, (const.PersonaChangeStati.pending,
                                                data['id'], current_generation))
                elif (current_state != committed_state
                        and self.is_relative_admin(rs, data['id'])):
                    # if user is relative admin, set pending change as reviewed
                    return self.changelog_resolve_change(
                        rs, data['id'], current_generation, ack=True)
                # We successfully made the data set match to the requested
                # values. It's not our fault, that we didn't have to do any work.
                # The change however may still be pending and awaiting review.
                #
                # The one case that's awkward here is that if a normal user
                # first tries to update multiple attributes some of which
                # require review causing a pending change and then tries in a
                # second attempt to only change uncritical attributes to
                # achieve an immediate resolve they will be stuck with the
                # pending change.
                rs.notify('info', n_("Nothing changed."))
                return 1
            # Determine if something requiring a review changed.
            fields_requiring_review = {
                "birthday", "family_name", "given_names", "birth_name",
                "gender", "address_supplement", "address", "postal_code",
                "location", "country", "donation",
            }
            # Special care is necessary in case of an existing pending
            # change. In this case we blend the new changes with the existing
            # pending change and then try to apply this fused change
            # superseeding the previous pending change. In most cases this
            # will result in a new pending change, however it's also possible
            # to revert all pending changes requiring review and thus the
            # fused change may directly apply.
            #
            # This way the history is somewhat sane and pretty much linear. We
            # don't want multiple pending changes or changes that apply by
            # half -- this should devolve into an overly complex resolution
            # tool for arbitrary conflicts (use git for that).
            new_state = current_state | data
            all_changed_fields = {key for key, value in new_state.items()
                                  if value != committed_state[key]}
            requires_review = (
                    all_changed_fields & fields_requiring_review
                    and current_state['is_event_realm']
                    and not self.is_relative_admin(rs, data['id']))

            # prepare for inserting a new changelog entry
            query = glue("SELECT MAX(generation) AS gen FROM core.changelog",
                         "WHERE persona_id = %s")
            max_gen = unwrap(self.query_one(rs, query, (data['id'],))) or 1
            next_generation = max_gen + 1
            # the following is a nop if there is no pending change
            query = glue("UPDATE core.changelog SET code = %s",
                         "WHERE persona_id = %s AND code = %s")
            self.query_exec(rs, query, (
                const.PersonaChangeStati.superseded, data['id'],
                const.PersonaChangeStati.pending))

            # insert new changelog entry
            insert = copy.deepcopy(current_state)
            insert.update(data)
            insert.update({
                "submitted_by": rs.user.persona_id,
                "reviewed_by": None,
                "generation": next_generation,
                "change_note": change_note,
                "code": const.PersonaChangeStati.pending,
                "persona_id": data['id'],
                "automated_change": automated_change,
            })
            del insert['id']
            if 'ctime' in insert:
                del insert['ctime']
            self.sql_insert(rs, "core.changelog", insert)

            # resolve change if it doesn't require review
            if (self.conf["CDEDB_OFFLINE_DEPLOYMENT"]
                    or (not force_review and not requires_review)):
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
                    "reviewed_by": None,
                    "generation": next_generation + 1,
                    "change_note": "Verdrängte Änderung.",
                    "code": const.PersonaChangeStati.pending,
                    "persona_id": data['id'],
                    "automated_change": automated_change,
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
        :param reviewed: Signals whether the change was reviewed. This exists,
          so that automatically resolved changes are not marked as reviewed.
        """
        if not ack:
            query = glue(
                "UPDATE core.changelog SET reviewed_by = %s,",
                "code = %s",
                "WHERE persona_id = %s AND code = %s",
                "AND generation = %s")
            return self.query_exec(rs, query, (
                rs.user.persona_id, const.PersonaChangeStati.nacked, persona_id,
                const.PersonaChangeStati.pending, generation))
        with Atomizer(rs):
            # look up changelog entry and mark as committed
            history = self.changelog_get_history(rs, persona_id,
                                                 generations=(generation,))
            data = history[generation]
            if data['code'] != const.PersonaChangeStati.pending:
                return 0
            query = "UPDATE core.changelog SET {setters} WHERE {conditions}"
            setters = ["code = %s"]
            params: list[Any] = [const.PersonaChangeStati.committed]
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
            if len(udata) == 1:
                rs.notify('warning', n_("Change has reverted pending change."))
                return 1
            elif len(udata) > 1:
                ret = self.commit_persona(rs, udata)
                if not ret:
                    raise RuntimeError(n_("Modification failed."))
        return ret

    @access("core_admin", "cde_admin", "event_admin")
    def changelog_resolve_change(self, rs: RequestState, persona_id: int,
                                 generation: int, ack: bool) -> DefaultReturnCode:
        if not self.is_relative_admin(rs, persona_id):
            raise PrivilegeError(n_("Not a relative admin."))
        return self._changelog_resolve_change_unsafe(rs, persona_id, generation, ack)

    @access("persona")
    def changelog_get_generations(
            self, rs: RequestState, ids: Collection[int], committed_only: bool = False,
    ) -> dict[int, int]:
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :param committed_only: Include only committed entries of the changelog.
        :returns: dict mapping ids to generations
        """
        query = glue("SELECT persona_id, max(generation) AS generation",
                     "FROM core.changelog WHERE persona_id = ANY(%s)",
                     "AND code = ANY(%s) GROUP BY persona_id")
        valid_status: tuple[const.PersonaChangeStati, ...]
        if committed_only:
            valid_status = (const.PersonaChangeStati.committed, )
        else:
            valid_status = (const.PersonaChangeStati.pending,
                            const.PersonaChangeStati.committed)
        data = self.query_all(rs, query, (ids, valid_status))
        return {e['persona_id']: e['generation'] for e in data}

    class _ChangelogGetGenerationProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int,
                     committed_only: bool = False) -> int: ...
    changelog_get_generation: _ChangelogGetGenerationProtocol = singularize(
        changelog_get_generations)

    @access("core_admin", "cde_admin", "event_admin")
    def changelog_get_pending_changes(self, rs: RequestState) -> CdEDBObjectMap:
        """Retrieve pending changes in the changelog.

        Only show changes for realms the respective admin has access too."""
        clearances = []
        if 'core_admin' not in rs.user.roles:
            for admin_role in {"cde_admin", "event_admin"}.intersection(rs.user.roles):
                realm = admin_role.removesuffix("_admin")
                higher_realms = implying_realms(realm)
                clearance = f"is_{realm}_realm = TRUE"
                for higher_realm in higher_realms:
                    clearance += f" AND NOT is_{higher_realm}_realm = TRUE"
                clearances.append(clearance)
        query = ("SELECT persona_id, given_names, display_name, family_name,"
                 " generation, ctime FROM core.changelog WHERE code = %s")
        if clearances:
            query = query + " AND (" + " OR ".join(clearances) + ")"
        data = self.query_all(rs, query, (const.PersonaChangeStati.pending,))
        return {e['persona_id']: e for e in data}

    @access("persona")
    def changelog_get_history(self, rs: RequestState, persona_id: int,
                              generations: Optional[Collection[int]],
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
                       "code", "change_note", "automated_change"))
        query = "SELECT {fields} FROM core.changelog WHERE {conditions}"
        conditions = ["persona_id = %s"]
        params: list[Any] = [persona_id]
        if generations:
            conditions.append("generation = ANY(%s)")
            params.append(generations)
        query = query.format(fields=', '.join(fields),
                             conditions=' AND '.join(conditions))
        data = self.query_all(rs, query, params)
        ret = {}
        for d in data:
            if d.get('gender'):
                d['gender'] = const.Genders(d['gender'])
            ret[d['generation']] = d
        return ret

    @internal
    @access("persona", "droid")
    def retrieve_personas(self, rs: RequestState, persona_ids: Collection[int],
                          columns: tuple[str, ...] = PERSONA_CORE_FIELDS,
                          ) -> CdEDBObjectMap:
        """Helper to access a persona dataset.

        Most of the time a higher level function like
        :py:meth:`get_personas` should be used.
        """
        if "id" not in columns:
            columns += ("id",)
        data = self.sql_select(rs, "core.personas", columns, persona_ids)
        ret = {}
        for d in data:
            if d.get('gender'):
                d['gender'] = const.Genders(d['gender'])
            ret[d['id']] = d
        return ret

    class _RetrievePersonaProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int,
                     columns: tuple[str, ...] = PERSONA_CORE_FIELDS) -> CdEDBObject: ...
    retrieve_persona: _RetrievePersonaProtocol = singularize(
        retrieve_personas, "persona_ids", "persona_id")

    @internal
    @access("ml")
    def list_all_personas(self, rs: RequestState, is_active: bool = False) -> set[int]:
        query = "SELECT id from core.personas WHERE is_archived = False"
        if is_active:
            query += " AND is_active = True"
        data = self.query_all(rs, query, params=tuple())
        return {e["id"] for e in data}

    @internal
    @access("ml")
    def list_current_members(self, rs: RequestState, is_active: bool = False,
                             ) -> set[int]:
        """Helper to list all current members.

        Used to determine subscribers of mandatory/opt-out member mailinglists.
        """
        query = "SELECT id from core.personas WHERE is_member = True"
        if is_active:
            query += " AND is_active = True"
        data = self.query_all(rs, query, params=tuple())
        return {e["id"] for e in data}

    @internal
    @access("ml")
    def list_all_moderators(self, rs: RequestState,
                            ml_types: Optional[
                                Collection[const.MailinglistTypes]] = None,
                            ) -> set[int]:
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
                     is_archived: Optional[bool],
                     is_cde_realm: Optional[bool] = None,
                     paper_expuls: Optional[bool] = None) -> Optional[int]:
        """Look up the following persona.

        :param is_member: If not None, only consider personas with a matching flag.
        :param is_archived: If not None, only consider personas with a matching flag.
        :param is_cde_realm: If not None, only consider personas with a matching flag.
        :param paper_expuls: If not None, only consider personas with a matching flag.

        :returns: Next valid id in table core.personas
        """
        persona_id = affirm_optional(int, persona_id)
        is_member = affirm_optional(bool, is_member)
        is_archived = affirm_optional(bool, is_archived)
        paper_expuls = affirm_optional(bool, paper_expuls)
        query = "SELECT MIN(id) FROM core.personas"
        constraints = []
        params: list[Any] = []
        if persona_id is not None:
            constraints.append("id > %s")
            params.append(persona_id)
        if is_member is not None:
            constraints.append("is_member = %s")
            params.append(is_member)
        if is_cde_realm is not None:
            constraints.append("is_cde_realm = %s")
            params.append(is_cde_realm)
        if is_archived is not None:
            constraints.append("is_archived = %s")
            params.append(is_archived)
        if paper_expuls is not None:
            constraints.append("paper_expuls = %s")
            params.append(paper_expuls)
        if constraints:
            query += " WHERE " + " AND ".join(constraints)
        return unwrap(self.query_one(rs, query, params))

    def commit_persona(self, rs: RequestState, data: CdEDBObject) -> DefaultReturnCode:
        """Actually update a persona data set.

        This is the innermost layer of the changelog functionality and
        actually modifies the core.personas table.
        """
        with Atomizer(rs):
            num = self.sql_update(rs, "core.personas", data)
            if not num:
                raise ValueError(n_("Nonexistent user."))
            current = self.retrieve_persona(rs, data['id'], columns=PERSONA_CDE_FIELDS)
            fulltext = self.create_fulltext(current)
            fulltext_update = {
                'id': data['id'],
                'fulltext': fulltext,
            }
            self.sql_update(rs, "core.personas", fulltext_update)
        return num

    @internal
    @access("persona")
    def set_persona(self, rs: RequestState, data: CdEDBObject,
                    generation: Optional[int] = None, change_note: Optional[str] = None,
                    may_wait: bool = True,
                    allow_specials: tuple[str, ...] = tuple(),
                    force_review: bool = False,
                    automated_change: bool = False,
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
        :param force_review: force a change to be reviewed, even if it may be committed
          without.
        """
        if not change_note:
            self.logger.info(f"No change note specified (persona_id={data['id']}).")
            change_note = "Allgemeine Änderung."

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
        if (set(data) & ADMIN_KEYS.keys()
                and ("meta_admin" not in rs.user.roles
                     or "admins" not in allow_specials)):
            if any(data[key] for key in ADMIN_KEYS):
                raise PrivilegeError(
                    n_("Admin privilege modification prevented."))
        if (set(data) & {"is_member", "trial_member", "honorary_member"}
                and (not ({"cde_admin", "core_admin"} & rs.user.roles)
                     or not {"membership", "purge"} & set(allow_specials))):
            raise PrivilegeError(n_("Membership modification prevented."))
        if (current['decided_search'] and not data.get("is_searchable", True)
                and (not ({"cde_admin", "core_admin"} & rs.user.roles))):
            raise PrivilegeError(n_("Hiding prevented."))
        if "is_archived" in data:
            if (not self.is_relative_admin(rs, data['id'], allow_meta_admin=False)
                    or "archive" not in allow_specials):
                raise PrivilegeError(n_("Archive modification prevented."))
        if ("balance" in data
                and ("cde_admin" not in rs.user.roles
                     or "finance" not in allow_specials)):
            # Allow setting balance to 0 or None during archival or membership change.
            if not ((data["balance"] is None or data["balance"] == 0)
                    and REALM_ADMINS & rs.user.roles
                    and {"archive", "purge", "membership"} & set(allow_specials)):
                raise PrivilegeError(n_("Modification of balance prevented."))
        if "username" in data and "username" not in allow_specials:
            raise PrivilegeError(n_("Modification of email address prevented."))
        if "foto" in data and "foto" not in allow_specials:
            raise PrivilegeError(n_("Modification of foto prevented."))
        if data.get("is_active") and rs.user.persona_id == data['id']:
            raise PrivilegeError(n_("Own activation prevented."))

        # check for permission to edit
        allow_meta_admin = data.keys() <= ADMIN_KEYS.keys() | {"id"}
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

        # This Atomizer is here to have a rollback in case of RuntimeError below.
        with Atomizer(rs):
            ret = self.changelog_submit_change(
                rs, data, generation=generation,
                may_wait=may_wait, change_note=change_note,
                force_review=force_review, automated_change=automated_change)
            if allow_specials and ret < 0:
                raise RuntimeError(n_("Special change not committed."))
        return ret

    @access("persona")
    def change_persona(self, rs: RequestState, data: CdEDBObject,
                       generation: Optional[int] = None, may_wait: bool = True,
                       change_note: Optional[str] = None,
                       force_review: bool = False) -> DefaultReturnCode:
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :param generation: generation on which this request is based, if this
          is not the current generation we abort, may be None to override
          the check
        :param may_wait: override for system requests (which may not wait)
        :param change_note: Descriptive line for changelog
        :param force_review: force a change to be reviewed, even if it may be committed
          without.
        """
        data = affirm(vtypes.Persona, data)
        generation = affirm_optional(int, generation)
        may_wait = affirm(bool, may_wait)
        change_note = affirm_optional(str, change_note)
        return self.set_persona(rs, data, generation=generation,
                                may_wait=may_wait, change_note=change_note,
                                force_review=force_review)

    @access("core_admin")
    def change_persona_realms(self, rs: RequestState, data: CdEDBObject,
                              change_note: str) -> DefaultReturnCode:
        """Special modification function for realm transitions."""
        data = affirm(vtypes.Persona, data, transition=True)
        change_note = affirm(str, change_note)
        ret = 1
        with Atomizer(rs):
            is_member = trial_member = honorary_member = None
            if data.get('is_cde_realm'):
                # Fix balance
                tmp = self.get_total_persona(rs, data['id'])
                if tmp['balance'] is None:
                    data['balance'] = decimal.Decimal('0.0')
                else:
                    data['balance'] = tmp['balance']
                # We can not apply the desired state directly, since this would violate
                #  our database integrity (but we also want to get the logs right), so
                #  we stash the changes here and apply them later on.
                is_member = data.get('is_member')
                trial_member = data.get('trial_member')
                honorary_member = data.get('honorary_member')
                data['is_member'] = data['trial_member'] = data['honorary_member'] =\
                    False
            ret *= self.set_persona(
                rs, data, may_wait=False, change_note=change_note,
                allow_specials=("realms", "finance", "membership"))
            self.core_log(
                rs, const.CoreLogCodes.realm_change, data['id'],
                change_note=change_note)
            # apply the previously stashed changes
            if is_member or trial_member or honorary_member:
                ret *= self.change_membership_easy_mode(
                    rs, data['id'], is_member=is_member, trial_member=trial_member,
                    honorary_member=honorary_member)
        return ret

    @access("cde")
    def get_foto_usage(self, rs: RequestState, file_hash: str) -> bool:
        file_hash = affirm(vtypes.RestrictiveIdentifier, file_hash)
        query = "SELECT COUNT(*) FROM core.personas WHERE foto = %s"
        return bool(unwrap(self.query_one(rs, query, (file_hash,))))

    @access("cde")
    def change_foto(self, rs: RequestState, persona_id: int,
                    new_hash: Optional[vtypes.Identifier]) -> DefaultReturnCode:
        """Special modification function for foto changes.

        Return 1 on successful change, -1 on successful removal, 0 otherwise.

        :param new_hash: Hash of new foto.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        old_hash: str = unwrap(self.sql_select_one(
            rs, "core.personas", ("foto",), persona_id))  # type: ignore[assignment]

        change_note = "Profilbild geändert." if new_hash else "Profilbild entfernt."
        # Evaluates to 1 if a new foto was provided, and to -1 otherwise.
        indicator = (-1) ** (bool(new_hash) + 1)
        if new_hash and not self.get_foto_store(rs).is_available(new_hash):
            raise RuntimeError(n_("File has been lost."))
        data: CdEDBObject = {
            'id': persona_id,
            'foto': new_hash,
        }
        ret = self.set_persona(rs, data, may_wait=False, change_note=change_note,
                               allow_specials=("foto",))
        if ret < 0:
            raise RuntimeError("Special persona change should not be pending.")
        if old_hash:
            self.get_foto_store(rs).forget_one(rs, self.get_foto_usage, old_hash)
        return ret * indicator

    @access("meta_admin")
    def initialize_privilege_change(self, rs: RequestState,
                                    data: CdEDBObject) -> DefaultReturnCode:
        """Initialize a change to a users admin bits.

        This has to be approved by another admin.
        """
        data['submitted_by'] = rs.user.persona_id
        data['status'] = const.PrivilegeChangeStati.pending
        data = affirm(vtypes.PrivilegeChange, data)

        if ("is_meta_admin" in data
                and data['persona_id'] == rs.user.persona_id):
            raise PrivilegeError(n_(
                "Cannot modify own meta admin privileges."))

        with Atomizer(rs):
            if self.list_privilege_changes(
                    rs, persona_id=data['persona_id'],
                    stati=(const.PrivilegeChangeStati.pending,)):
                raise ValueError(n_("Pending privilege change."))

            persona = self.get_total_persona(rs, data['persona_id'])

            # see also cdedb.frontend.templates.core.change_privileges
            # and change_privileges in cdedb.frontend.core

            errormsg = n_("User does not fit the requirements for this"
                          " admin privilege.")
            for admin, required in ADMIN_KEYS.items():
                if data.get(admin):
                    if data.get(required) is False:
                        raise ValueError(errormsg)
                    if not persona[required] and not data.get(required):
                        raise ValueError(errormsg)

            self.core_log(
                rs, const.CoreLogCodes.privilege_change_pending,
                data['persona_id'],
                change_note="Änderung der Admin-Privilegien angestoßen.")
            ret = self.sql_insert(rs, "core.privilege_changes", data)

        return ret

    @access("meta_admin")
    def finalize_privilege_change(self, rs: RequestState, privilege_change_id: int,
                                  case_status: const.PrivilegeChangeStati,
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
                    "id": case["persona_id"],
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
    def list_privilege_changes(self, rs: RequestState, persona_id: Optional[int] = None,
                               stati: Optional[Collection[
                                   const.PrivilegeChangeStati]] = None,
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
        params: list[Any] = []
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
        ret = {}
        for e in data:
            e['status'] = const.PrivilegeChangeStati(e['status'])
            ret[e['id']] = e
        return ret

    class _GetPrivilegeChangeProtocol(Protocol):
        def __call__(self, rs: RequestState, privilege_change_id: int,
                     ) -> CdEDBObject: ...
    get_privilege_change: _GetPrivilegeChangeProtocol = singularize(
        get_privilege_changes, "privilege_change_ids", "privilege_change_id")

    @access("persona")
    def list_admins(self, rs: RequestState, realm: str) -> list[int]:
        """List all personas with admin privilidges in a given realm."""
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
            "auditor": "is_auditor = TRUE",
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
                               change_note: Optional[str] = None,
                               transaction_date: Optional[datetime.date] = None,
                               ) -> DefaultReturnCode:
        """Special modification function for monetary aspects."""
        persona_id = affirm(vtypes.ID, persona_id)
        balance = affirm(vtypes.NonNegativeDecimal, balance)
        log_code = affirm(const.FinanceLogCodes, log_code)
        change_note = affirm_optional(str, change_note)
        transaction_date = affirm_optional(datetime.date, transaction_date)
        update: CdEDBObject = {
            'id': persona_id,
        }
        with Atomizer(rs):
            current = self.retrieve_persona(
                rs, persona_id, ("balance", "is_cde_realm", "trial_member"))
            if not current['is_cde_realm']:
                raise RuntimeError(
                    n_("Tried to credit balance to non-cde person."))
            if current['balance'] != balance:
                update['balance'] = balance
            if 'balance' in update:
                ret = self.set_persona(
                    rs, update, may_wait=False, change_note=change_note,
                    allow_specials=("finance",))
                self.finance_log(
                    rs, log_code, persona_id, balance - current['balance'], balance,
                    transaction_date=transaction_date)
                return ret
            else:
                return 0

    @access("core_admin", "cde_admin")
    def change_membership_easy_mode(self, rs: RequestState, persona_id: int, *,
                                    is_member: Optional[bool] = None,
                                    trial_member: Optional[bool] = None,
                                    honorary_member: Optional[bool] = None,
                                    ) -> DefaultReturnCode:
        """Special modification function for membership.

        This variant only works for easy cases, that is for gaining membership
        or if no active lastschrift permits exist. Otherwise (i.e. in the
        general case) the change_membership function from the cde-backend
        has to be used.

        :param is_member: Desired target state of membership or None.
        :param trial_member: Desired target state of trial membership or None.
        :param honorary_member: Desired target state of honorary membership or None.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        is_member = affirm_optional(bool, is_member)
        trial_member = affirm_optional(bool, trial_member)
        honorary_member = affirm_optional(bool, honorary_member)
        with Atomizer(rs):
            current = self.get_total_persona(rs, persona_id)

            # Determine target state.
            if is_member is None:
                is_member = current['is_member']
            if trial_member is None:
                trial_member = current['trial_member']
            if honorary_member is None:
                honorary_member = current['honorary_member']

            # Do some sanity checks
            if not current['is_cde_realm']:
                raise RuntimeError(n_("Not a CdE account."))
            if trial_member and not is_member:
                raise ValueError(n_("Trial membership requires membership."))
            if honorary_member and not is_member:
                raise ValueError(n_("Honorary membership requires membership."))

            if not is_member:
                # Peek at the CdE-realm, this is somewhat of a transgression,
                # but sadly necessary duct tape to keep the whole thing working.
                query = ("SELECT id FROM cde.lastschrift"
                         " WHERE persona_id = %s AND revoked_at IS NULL")
                params = [persona_id]
                if self.query_all(rs, query, params):
                    raise RuntimeError(n_("Active lastschrift permit found."))

            # check if nothing changed at all
            if (
                is_member == current['is_member']
                and trial_member == current['trial_member']
                and honorary_member == current['honorary_member']
            ):
                rs.notify('info', n_("Nothing changed."))
                return 1

            update: CdEDBObject = {
                'id': persona_id,
                'is_member': is_member,
                'trial_member': trial_member,
                'honorary_member': honorary_member,
            }
            ret = self.set_persona(
                rs, update, may_wait=False,
                change_note="Mitgliedschaftsstatus geändert.",
                allow_specials=("membership",))

            # Perform logging
            if is_member != current['is_member']:
                if is_member:
                    code = const.FinanceLogCodes.gain_membership
                else:
                    code = const.FinanceLogCodes.lose_membership
                self.finance_log(rs, code, persona_id, delta=None, new_balance=None)
            if trial_member != current['trial_member']:
                if trial_member:
                    code = const.FinanceLogCodes.start_trial_membership
                else:
                    code = const.FinanceLogCodes.end_trial_membership
                self.finance_log(rs, code, persona_id, delta=None, new_balance=None)
            if honorary_member != current['honorary_member']:
                if honorary_member:
                    code = const.FinanceLogCodes.honorary_membership_granted
                else:
                    code = const.FinanceLogCodes.honorary_membership_revoked
                self.finance_log(rs, code, persona_id, delta=None, new_balance=None)
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
    def get_persona_latest_session(self, rs: RequestState, persona_id: int,
                                   ) -> Optional[datetime.datetime]:
        """Retrieve the time of a users latest session.

        Returns None if there are no active sessions on record.
        """
        persona_id = affirm(vtypes.ID, persona_id)

        query = "SELECT MAX(atime) AS atime FROM core.sessions WHERE persona_id = %s"
        return unwrap(self.query_one(rs, query, (persona_id,)))

    @access("core_admin")
    def is_persona_automatically_archivable(
            self, rs: RequestState, persona_id: int,
            reference_date: Optional[datetime.date] = None,
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
            * The persona having been manually changed/created in the last two years.
            * The persona being involved (orga/registration) with any recent event.
            * The persona being involved (presider/attendee) with an active assembly.
            * The persona being a pure assembly user.
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

            # Pure assembly users represent external representants for our assemblies.
            # As assemblies are rare and they do not need to log in to participate,
            # the archival would catch many false positives.
            if persona['is_assembly_realm'] and not persona['is_cde_realm']:
                return False

            # Check latest user session.
            latest_session = self.get_persona_latest_session(rs, persona_id)
            if latest_session is not None and latest_session.date() > cutoff:
                return False

            # Check that the latest update to the persona was before the cutoff date.
            # Normally we would utilize self.changelog_get_generation() to retrieve
            # `generation`, but we exclude automated script changes here.
            query = ("SELECT MAX(generation) FROM core.changelog"
                     " WHERE persona_id = %s AND automated_change = FALSE")
            generation = unwrap(self.query_one(rs, query, (persona_id,)))
            if not generation:
                # Something strange is going on, so better not do anything.
                self.logger.error(f"No valid generation seems to exist for persona"
                                  f" {persona_id}.")
                return False
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
                const.SubscriptionState.subscribed,
                const.SubscriptionState.subscription_override,
                const.SubscriptionState.pending,
            }
            if self.query_all(rs, query, (persona_id, states)):
                return False

        return True

    @access(*REALM_ADMINS)
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
            if not self.is_relative_admin(rs, persona_id, allow_meta_admin=False):
                raise ArchiveError(n_("You are not allowed to archive this user."))

            if persona['is_archived']:
                return 0

            # Disallow archival of admins. Admin privileges should be unset
            # by two meta admins before.
            if any(persona[key] for key in ADMIN_KEYS):
                raise ArchiveError(n_("Cannot archive admins."))

            #
            # 2. Handle lastschrift
            #
            lastschrift = self.sql_select(
                rs, "cde.lastschrift", ("id", "revoked_at"), (persona_id,),
                entity_key="persona_id")
            if any(not ls['revoked_at'] for ls in lastschrift):
                raise ArchiveError(n_("Active lastschrift exists."))
            query = ("UPDATE cde.lastschrift"
                     " SET (iban, account_owner, account_address)"
                     " = (%s, %s, %s)"
                     " WHERE persona_id = %s"
                     " AND revoked_at < now() - interval '14 month'")
            if lastschrift:
                self.query_exec(rs, query, ("", "", "", persona_id))
            #
            # 3. Remove complicated attributes ([trial] membership, foto and password)
            #
            if persona['is_member']:
                code = self.change_membership_easy_mode(
                    rs, persona_id, is_member=False, trial_member=False,
                    honorary_member=False)
                if not code:
                    raise ArchiveError(n_("Failed to revoke membership."))
            if persona['foto']:
                code = self.change_foto(rs, persona_id, new_hash=None)
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
            # 4. Strip all unnecessary attributes and mark as archived
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
                'is_auditor': False,
                # Do no touch the realms, to preserve integrity and
                # allow reactivation.
                # 'is_cde_realm'
                # 'is_event_realm'
                # 'is_ml_realm'
                # 'is_assembly_realm'
                # 'is_member' already adjusted
                'is_searchable': False,
                'is_archived': True,
                # 'is_purged' not relevant here
                # 'display_name' kept for later recognition
                # 'given_names' kept for later recognition
                # 'family_name' kept for later recognition
                'title': None,
                'name_supplement': None,
                # 'gender' kept for later recognition
                'pronouns': None,
                'pronouns_profile': False,
                'pronouns_nametag': False,
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
                'donation': 0 if persona['donation'] is not None else None,
                'decided_search': False if persona['is_cde_realm'] else None,
                # 'trial_member' already adjusted
                'bub_search': False if persona['is_cde_realm'] else None,
                'paper_expuls': True if persona['is_cde_realm'] else None,
                # 'foto' already adjusted
                # 'fulltext' is set automatically
            }
            self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Archivierung vorbereitet.",
                allow_specials=("archive", "username"))
            #
            # 5. Delete all sessions and quotas
            #
            self.sql_delete(rs, "core.sessions", (persona_id,), "persona_id")
            self.sql_delete(rs, "core.quota", (persona_id,), "persona_id")
            #
            # 6. Handle event realm
            #
            query = glue(
                "SELECT reg.persona_id, MAX(part_end) AS m",
                "FROM event.registrations as reg ",
                "JOIN event.events as event ON reg.event_id = event.id",
                "JOIN event.event_parts as parts ON parts.event_id = event.id",
                "WHERE reg.persona_id = %s",
                "GROUP BY persona_id")
            max_end = self.query_one(rs, query, (persona_id,))
            if max_end and max_end['m'] and max_end['m'] >= now().date():
                raise ArchiveError(n_("Involved in unfinished event."))
            self.sql_delete(rs, "event.orgas", (persona_id,), "persona_id")
            #
            # 7. Assembly realm is handled via assembly archival.
            #
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
                unmoderated_mailinglists = moderated_mailinglists - ml_ids
                if unmoderated_mailinglists:
                    raise ArchiveError(
                        n_("Sole moderator of a mailinglist %(ml_ids)s."),
                        {'ml_ids': unmoderated_mailinglists})
            #
            # 9. Clear logs
            #
            self.sql_delete(rs, "core.log", (persona_id,), "persona_id")
            # finance log stays untouched to keep balance correct
            # therefore, we log if the persona had any remaining balance
            if persona["balance"]:
                log_code = const.FinanceLogCodes.remove_balance_on_archival
                self.finance_log(rs, log_code, persona_id, delta=-persona['balance'],
                                 new_balance=decimal.Decimal("0"))
            # The cde.log does not store user specific data
            # self.sql_delete(rs, "cde.log", (persona_id,), "persona_id")
            # past event log stays untouched since we keep past events
            # event log stays untouched since events have a separate life cycle
            # assembly log stays since assemblies have a separate life cycle
            self.sql_delete(rs, "ml.log", (persona_id,), "persona_id")
            #
            # 10. Create archival log entry
            #
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

    @access(*REALM_ADMINS)
    def dearchive_persona(self, rs: RequestState, persona_id: int, new_username: str,
                          ) -> DefaultReturnCode:
        """Return a persona from the attic to activity.

        This does nothing but flip the archiving bit and set a new username,
        which makes sure the resulting persona will pass validation.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        new_username = affirm(vtypes.Email, new_username)
        with Atomizer(rs):
            if self.verify_existence(rs, new_username):
                raise ValueError(n_("User with this E-Mail exists already."))
            update = {
                'id': persona_id,
                'is_archived': False,
                'is_active': True,
                'username': new_username,
            }
            code = self.set_persona(
                rs, update, generation=None, may_wait=False,
                change_note="Benutzer aus dem Archiv wiederhergestellt.",
                allow_specials=("archive", "username"))
            self.core_log(rs, const.CoreLogCodes.persona_dearchived, persona_id)
        return code

    @access("core_admin")
    def purge_persona(self, rs: RequestState, persona_id: int) -> DefaultReturnCode:
        """Delete all infos about this persona.

        It has to be archived beforehand. Thus we do not have to
        remove a lot since archiving takes care of most of the stuff.

        However we do not entirely delete the entry since this would
        cause havock in other areas (like assemblies), we only
        anonymize the entry by removing all identifying information.
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
                'birthday': datetime.date.min,
                'birth_name': None,
                'gender': const.Genders.not_specified,
                'is_cde_realm': True,
                'is_event_realm': True,
                'is_ml_realm': True,
                'is_assembly_realm': True,
                'is_purged': True,
                'balance': 0,
                'donation': 0,
                'decided_search': False,
                'trial_member': False,
                'honorary_member': False,
                'bub_search': False,
                'paper_expuls': True,
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
            query = "DELETE FROM core.changelog WHERE persona_id = %s AND NOT id = %s"
            ret *= self.query_exec(rs, query, (persona_id, newest['id']))
            #
            # 4. Finish
            #
            self.core_log(rs, const.CoreLogCodes.persona_purged, persona_id)
            return ret

    @access("persona")
    def change_username(self, rs: RequestState, persona_id: int,
                        new_username: str, password: Optional[str],
                        ) -> tuple[bool, str]:
        """Since usernames are used for login, this needs a bit of care.

        :returns: The bool signals whether the change was successful, the str
            is an error message or the new username on success.
        """
        persona_id = affirm(vtypes.ID, persona_id)
        new_username = affirm(vtypes.Email, new_username)
        password = affirm_optional(str, password)
        with Atomizer(rs):
            if self.verify_existence(rs, new_username):
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
                    return True, new_username
        return False, n_("Failed.")

    @access("persona")
    def foto_usage(self, rs: RequestState, foto: str) -> int:
        """Retrieve usage number for a specific foto.

        So we know when a foto is up for garbage collection."""
        foto = affirm(str, foto)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE foto = %s"
        return unwrap(self.query_one(rs, query, (foto,))) or 0

    @access("persona")
    def get_personas(self, rs: RequestState, persona_ids: Collection[int],
                     ) -> CdEDBObjectMap:
        """Acquire data sets for specified ids."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        return self.retrieve_personas(rs, persona_ids, columns=PERSONA_CORE_FIELDS)

    class _GetPersonaProtocol(Protocol):
        # TODO: `persona_id` is actually not optional, but it produces a lot of errors.
        def __call__(self, rs: RequestState, persona_id: Optional[int],
                     ) -> CdEDBObject: ...
    get_persona: _GetPersonaProtocol = singularize(
        get_personas, "persona_ids", "persona_id")

    @access("event", "droid_quick_partial_export", "droid_orga")
    def get_event_users(self, rs: RequestState, persona_ids: Collection[int],
                        event_id: Optional[int] = None) -> CdEDBObjectMap:
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
        is_orga = False
        if event_id:
            is_orga = event_id in rs.user.orga
        if (persona_ids != {rs.user.persona_id}
                and not (rs.user.roles
                         & {"event_admin", "cde_admin", "core_admin",
                            "droid_quick_partial_export"})):
            # Accessing the event scheme from the core backend is a bit of a
            # transgression, but we value the added security higher than correctness.
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
            params: list[Any] = [event_id]
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
                     event_id: Optional[int] = None) -> CdEDBObject: ...
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
    def quota(self, rs: RequestState, *, ids: Optional[Collection[int]] = None,
              num: Optional[int] = None) -> int:
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
            access_hash = get_hash(str(xsorted(ids)).encode())
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
    def check_quota(self, rs: RequestState, *, ids: Optional[Collection[int]] = None,
                    num: Optional[int] = None) -> bool:
        """Check whether the quota was exceeded today.

        Even if quota has been exceeded, never block access to own profile.
        """
        # Validation is done inside.
        if num is None and ids is not None and set(ids) == {rs.user.persona_id}:
            return False
        quota = self.quota(rs, ids=ids, num=num)  # type: ignore[call-overload]
        return (quota > self.conf["QUOTA_VIEWS_PER_DAY"]
                and not {"cde_admin", "core_admin"} & rs.user.roles)

    @access("cde")
    def get_cde_users(self, rs: RequestState, persona_ids: Collection[int],
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
    def get_ml_users(self, rs: RequestState, persona_ids: Collection[int],
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
    def get_assembly_users(self, rs: RequestState, persona_ids: Collection[int],
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
    def get_total_personas(self, rs: RequestState, persona_ids: Collection[int],
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

    @access(*REALM_ADMINS)
    def create_persona(self, rs: RequestState, data: CdEDBObject,
                       submitted_by: Optional[int] = None) -> DefaultReturnCode:
        """Instantiate a new data set.

        This does the house-keeping and inserts the corresponding entry in
        the changelog.

        :param submitted_by: Allow to override the submitter for genesis.
        :returns: The id of the newly created persona.
        """
        data = affirm(vtypes.Persona, data, creation=True)
        submitted_by = affirm_optional(vtypes.ID, submitted_by)
        # zap any admin attempts
        data.update({'is_archived': False, 'is_purged': False})
        data.update({k: False for k in ADMIN_KEYS})
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
        # For the sake of correct logging, we stash these as changes
        membership_keys = ('is_member', 'trial_member', 'honorary_member')
        stash = {k: data.pop(k) for k in membership_keys}
        data.update({
            'is_member': False,
            'trial_member': False if data.get('is_cde_realm') else None,
            'honorary_member': False if data.get('is_cde_realm') else None,
        })
        with Atomizer(rs):

            new_id = self.sql_insert(rs, "core.personas", data)
            data.update({
                "submitted_by": submitted_by or rs.user.persona_id,
                "generation": 1,
                "code": const.PersonaChangeStati.committed,
                "persona_id": new_id,
                "change_note": "Account erstellt.",
            })
            # remove unlogged attributes
            del data['password_hash']
            del data['fulltext']
            self.sql_insert(rs, "core.changelog", data)
            self.core_log(rs, const.CoreLogCodes.persona_creation, new_id)

            # apply the previously stashed changes
            if any(stash.values()):
                self.change_membership_easy_mode(rs, new_id, **stash)
        return new_id

    @access("anonymous")
    def login(self, rs: RequestState, username: str, password: str,
              ip: Optional[str]) -> Optional[str]:
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
        # TODO Extract IP address from RequestState
        ip = affirm(vtypes.PrintableASCII, ip)
        # note the lower-casing for email addresses
        query = ("SELECT id, is_meta_admin, is_core_admin FROM core.personas"
                 " WHERE username = lower(%s) AND is_active = True")
        data = self.query_one(rs, query, (username,))
        if not data or (
                not self.conf["CDEDB_OFFLINE_DEPLOYMENT"]
                and not self.verify_persona_password(rs, password, data["id"])):
            # log message to be picked up by fail2ban
            self.logger.warning(f"CdEDB login failure from {ip} for {username}")
            return None
        if self.is_locked_down(rs) and not (data['is_meta_admin']
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
        # Necessary to keep the mechanics happy.
        rs._conn = rs.conn  # pylint: disable=protected-access

        # Get more information about user (for immediate use in frontend)
        data = self.sql_select_one(rs, "core.personas",
                                   PERSONA_CORE_FIELDS, data["id"])
        if data is None:
            raise RuntimeError(n_("Impossible."))
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
        params: list[Any] = [rs.user.persona_id]
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

    @access("persona")
    def count_active_sessions(self, rs: RequestState) -> int:
        """Retrieve number of currently active sessions"""
        query = ("SELECT COUNT(*) FROM core.sessions"
                 " WHERE is_active = True AND persona_id = %s")
        count = unwrap(self.query_one(rs, query, (rs.user.persona_id,))) or 0
        return count

    @access("core_admin")
    def deactivate_old_sessions(self, rs: RequestState) -> DefaultReturnCode:
        """Deactivate old leftover sessions."""
        query = ("UPDATE core.sessions SET is_active = False"
                 " WHERE is_active = True AND atime < %s")
        # Choose longer interval than SESSION_LIFESPAN here to keep sessions active
        # if e.g. the lifespan config is increased at some time. Inactivation of
        # sessions based on lifetime is done in login and lookupsession methods.
        cutoff = now() - self.conf['SESSION_SAVETIME']
        return self.query_exec(rs, query, (cutoff, ))

    @access("core_admin")
    def clean_session_log(self, rs: RequestState) -> DefaultReturnCode:
        """Delete old entries from the sessionlog."""
        query = ("DELETE FROM core.sessions WHERE is_active = False"
                 " AND atime < %s"
                 " AND (persona_id, atime) NOT IN"
                 " (SELECT persona_id, MAX(atime) AS atime FROM core.sessions"
                 "  WHERE is_active = False GROUP BY persona_id)")
        cutoff = now() - self.conf['SESSION_SAVETIME']
        return self.query_exec(rs, query, (cutoff,))

    @access("persona")
    def verify_ids(self, rs: RequestState, persona_ids: Collection[int],
                   is_archived: Optional[bool] = None) -> bool:
        """Check that persona ids do exist.

        :param is_archived: If given, check the given archival status.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        is_archived = affirm_optional(bool, is_archived)
        if persona_ids == {rs.user.persona_id}:
            return True
        query = "SELECT COUNT(*) AS num FROM core.personas"
        constraints: list[str] = ["id = ANY(%s)"]
        params: list[Any] = [persona_ids]
        if is_archived is not None:
            constraints.append("is_archived = %s")
            params.append(is_archived)

        if constraints:
            query += " WHERE " + " AND ".join(constraints)
        num = unwrap(self.query_one(rs, query, params))
        return num == len(persona_ids)

    class _VerifyIDProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int,
                     is_archived: Optional[bool] = None) -> bool: ...
    verify_id: _VerifyIDProtocol = singularize(
        verify_ids, "persona_ids", "persona_id", passthrough=True)

    @internal
    @access("anonymous")
    def get_roles_multi(self, rs: RequestState, persona_ids: Collection[int],
                        introspection_only: bool = False,
                        ) -> dict[Optional[int], set[Role]]:
        """Resolve ids into roles.

        Returns an empty role set for inactive users."""
        if set(persona_ids) == {rs.user.persona_id}:
            return {rs.user.persona_id: rs.user.roles}
        bits = PERSONA_STATUS_FIELDS + ("id",)
        data = self.sql_select(rs, "core.personas", bits, persona_ids)
        return {d['id']: extract_roles(d, introspection_only) for d in data}

    class _GetRolesSingleProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: Optional[int],
                     introspection_only: bool = False) -> set[Role]: ...
    get_roles_single: _GetRolesSingleProtocol = singularize(get_roles_multi)

    @access("persona")
    def verify_personas(self, rs: RequestState, persona_ids: Collection[int],
                        required_roles: Optional[Collection[Role]] = None,
                        allowed_roles: Optional[Collection[Role]] = None,
                        introspection_only: bool = True) -> bool:
        """Check whether certain ids map to actual (active) personas.

        Note that this will return True for an empty set of ids.

        :param required_roles: If given, check that all personas have these roles.
        :param allowed_roles: If given, check that all personas roles are a subset of
            these.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        required_roles = required_roles or tuple()
        required_roles = affirm_set(str, required_roles)
        allowed_roles = allowed_roles or ALL_ROLES
        allowed_roles = affirm_set(str, allowed_roles)
        # add always allowed roles for personas
        allowed_roles |= {"persona", "anonymous"}
        roles = self.get_roles_multi(rs, persona_ids, introspection_only)
        return (len(roles) == len(persona_ids)
            and all(value >= required_roles for value in roles.values())
            and all(allowed_roles >= value for value in roles.values()))

    class _VerifyPersonaProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int,
                     required_roles: Optional[Collection[Role]] = None,
                     allowed_roles: Optional[Collection[Role]] = None,
                     introspection_only: bool = True) -> bool: ...
    verify_persona: _VerifyPersonaProtocol = singularize(
        verify_personas, "persona_ids", "persona_id", passthrough=True)

    @access("anonymous")
    def verify_existence(self, rs: RequestState, email: str,
                         include_genesis: bool = True) -> bool:
        """Check whether a certain email belongs to any persona."""
        email = affirm(vtypes.Email, email)
        query = "SELECT COUNT(*) AS num FROM core.personas WHERE username = %s"
        num = unwrap(self.query_one(rs, query, (email,))) or 0
        if include_genesis:
            query = glue("SELECT COUNT(*) AS num FROM core.genesis_cases",
                         "WHERE username = %s AND case_status = ANY(%s)")
            # This should be all stati which are not final.
            stati = set(const.GenesisStati) - const.GenesisStati.finalized_stati()
            num += unwrap(self.query_one(rs, query, (email, stati))) or 0
        return bool(num)

    RESET_COOKIE_PAYLOAD = "X"

    def _generate_reset_cookie(
            self, rs: RequestState, persona_id: int, salt: str,
            timeout: datetime.timedelta = datetime.timedelta(seconds=60),
    ) -> str:
        """Create a cookie which authorizes a specific reset action.

        The cookie depends on the inputs as well as a server side secret.
        """
        password_hash = unwrap(self.sql_select_one(
            rs, "core.personas", ("password_hash",), persona_id))
        if password_hash is None:
            # A personas password hash cannot be empty.
            raise ValueError(n_("Persona does not exist."))

        if not self.is_admin(rs) and "meta_admin" not in rs.user.roles:
            roles = self.get_roles_single(rs, persona_id)
            if any("admin" in role for role in roles):
                raise PrivilegeError(n_("Preventing reset of admin."))

        # This defines a specific account/password combination as purpose
        cookie = encode_parameter(
            salt, str(persona_id), password_hash,
            self.RESET_COOKIE_PAYLOAD, persona_id=None, timeout=timeout)
        return cookie

    def _verify_reset_cookie(self, rs: RequestState, persona_id: int, salt: str,
                             cookie: str) -> Optional[str]:
        """Check a provided cookie for correctness.

        :returns: None on success, an error message otherwise.
        """
        password_hash = unwrap(self.sql_select_one(
            rs, "core.personas", ("password_hash",), persona_id))
        if password_hash is None:
            # A personas password hash cannot be empty.
            raise ValueError(n_("Persona does not exist."))
        timeout, msg = decode_parameter(
            salt, str(persona_id), password_hash, cookie, persona_id=None)
        if msg is None:
            if timeout:
                return n_("Link expired.")
            else:
                return n_("Link invalid or already used.")
        if msg != self.RESET_COOKIE_PAYLOAD:
            return n_("Link invalid or already used.")
        return None

    def modify_password(self, rs: RequestState, new_password: str,
                        old_password: Optional[str] = None,
                        reset_cookie: Optional[str] = None,
                        persona_id: Optional[int] = None) -> tuple[bool, str]:
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
            msg = self.verify_reset_cookie(rs, persona_id, reset_cookie)
            if msg is not None:
                return False, msg
        if not new_password:
            return False, n_("No new password provided.")
        _, errs = inspect(vtypes.PasswordStrength, new_password)
        if errs:
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
        return bool(ret), new_password

    @access("persona")
    def change_password(self, rs: RequestState, old_password: str,
                        new_password: str) -> tuple[bool, str]:
        """
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
        email: Optional[str] = None, persona_id: Optional[int] = None,
        argname: Optional[str] = None,
    ) -> tuple[Optional[vtypes.PasswordStrength], list[Error]]:
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
        elif email:
            persona_id = unwrap(self.sql_select_one(
                rs, "core.personas", ("id",), email, entity_key="username"))
            if persona_id is None:
                raise ValueError(n_("Unknown email address."))
        assert persona_id is not None

        columns_of_interest = [
            *ADMIN_KEYS, "username", "given_names", "family_name", "display_name",
            "title", "name_supplement", "birthday",
        ]

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

        admin = any(persona[admin] for admin in ADMIN_KEYS)
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

        password, errs = inspect(vtypes.PasswordStrength, password, argname=argname,
                                 admin=admin, inputs=inputs)

        return password, errs

    @access("anonymous")
    def make_reset_cookie(self, rs: RequestState, email: str,
                          timeout: datetime.timedelta = datetime.timedelta(
                              seconds=60)) -> tuple[bool, str]:
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
                       cookie: str) -> tuple[bool, str]:
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
        if self.is_locked_down(rs):
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

    @access("core_admin", *(f"{realm}_admin"
                            for realm in REALM_SPECIFIC_GENESIS_FIELDS))
    def find_doppelgangers(self, rs: RequestState,
                           persona: CdEDBObject) -> CdEDBObjectMap:
        """Look for accounts with data similar to the passed dataset.

        This is for batch admission, where we may encounter datasets to
        already existing accounts. In that case we do not want to create
        a new account. It is also used during genesis to avoid creation
        of duplicate accounts.

        :returns: A dict of possibly matching account data.
        """
        persona = affirm(vtypes.Persona, persona, _ignore_warnings=True)
        if persona['birthday'] == datetime.date.min:
            persona['birthday'] = None
        scores: dict[int, int] = collections.defaultdict(lambda: 0)
        queries: list[tuple[int, str, tuple[Any, ...]]] = [
            (10, "given_names = %s OR display_name = %s",
             (persona['given_names'], persona['given_names'])),
            (10, "family_name = %s OR birth_name = %s",
             (persona['family_name'], persona['family_name'])),
            (10, "family_name = %s OR birth_name = %s",
             (persona['birth_name'], persona['birth_name'])),
            (10, "birthday = %s", (persona['birthday'],)),
            (5, "location = %s", (persona['location'],)),
            (5, "postal_code = %s", (persona['postal_code'],)),
            (20, "(given_names = %s OR display_name = %s) AND family_name = %s",
             (persona['given_names'], persona['given_names'], persona['family_name'])),
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
        # Circumvent privilege check, since this is a rather special case.
        ret = self.retrieve_personas(
            rs, persona_ids, PERSONA_CORE_FIELDS + ("birthday",))
        for persona_id, persona_ in ret.items():
            persona_['may_be_edited'] = self._is_relative_admin(rs, persona_)
        return ret

    @access("persona")
    def log_anonymous_message(
            self, rs: RequestState, message: models.AnonymousMessageData,
    ) -> Optional[str]:
        """Save encrypted metadata regarding an anonymous message sent via contact form.

        This is so that one may reply to the anonymous message without needing to know
        who sent it.
        """

        message = affirm_dataclass(models.AnonymousMessageData, message, creation=True)

        with Atomizer(rs):
            if self.sql_insert(
                rs, models.AnonymousMessageData.database_table, message.to_database(),
            ):
                self.core_log(
                    rs, const.CoreLogCodes.send_anonymous_message,
                    change_note=message.recipient, suppress_persona_id=True,
                )
                return message.message_id
        return None

    @access("persona")
    def get_anonymous_message(
            self, rs: RequestState, message_id: str,
    ) -> models.AnonymousMessageData:
        """Retrieve the metadata for an anonymous message using a unique message id.

        Note that the message id is a random base64 string, not a numeric id, even
        though the stored message _also_ has a numeric id.
        """

        affirm(vtypes.Base64, message_id)

        message_data = self.sql_select_one(
            rs, models.AnonymousMessageData.database_table,
            models.AnonymousMessageData.database_fields(),
            message_id, models.AnonymousMessageData.entity_key,
        )
        if not message_data:
            self.logger.error(
                f"User {rs.user.persona_id} tried to retrieve an anonymous message"
                f" using an invalid message id {message_id}.")
            raise KeyError(n_("Unknown message id."))

        return models.AnonymousMessageData.from_database(message_data)

    @access("persona")
    def rotate_anonymous_message(
            self, rs: RequestState, message: models.AnonymousMessageData,
    ) -> Optional[str]:
        """Update the encryption key, and the message id of a stored anonymous message.

        This is to be done should the message id (including the key) leak.
        """

        message = affirm_dataclass(models.AnonymousMessageData, message)

        update = message.to_database()
        del update['ctime']
        del update['recipient']

        with Atomizer(rs):
            if self.sql_update(
                rs, models.AnonymousMessageData.database_table, update,
            ):
                self.logger.info(
                    f"Rotated encryption key and message id for anonymous"
                    f" message {message.id}")
                self.core_log(
                    rs, const.CoreLogCodes.rotate_anonymous_message,
                    change_note=message.recipient,
                )
                return message.message_id
        return None

    @access("anonymous")
    def get_meta_info(self, rs: RequestState) -> CdEDBObject:
        """Retrieve changing info about the DB and the CdE e.V.

        This is a relatively painless way to specify lots of constants
        like who is responsible for donation certificates.
        """
        query = "SELECT info FROM core.meta_info LIMIT 1"
        data = unwrap(self.query_one(rs, query, tuple())) or {}
        return {field: data.get(field) for field in META_INFO_FIELDS}

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

    @access("anonymous")
    def is_locked_down(self, rs: RequestState) -> bool:
        """Helper to determine whether the CdEDB is currently locked."""
        return bool(self.conf["LOCKDOWN"] or self.get_meta_info(rs).get("lockdown_web"))

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

    def _submit_general_query(self, rs: RequestState, query: Query,
                              aggregate: bool = False) -> tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.
        """
        query = affirm(Query, query)
        aggregate = affirm(bool, aggregate)
        if query.scope == QueryScope.core_user:
            query.constraints.append(("is_archived", QueryOperators.equal, False))
        elif query.scope == QueryScope.all_core_users:
            pass
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query, aggregate=aggregate)
    submit_general_query = access("core_admin")(_submit_general_query)

    @access("persona")
    def submit_select_persona_query(self, rs: RequestState,
                                    query: Query) -> tuple[CdEDBObject, ...]:
        """Accessible version of :py:meth:`submit_general_query`.

        This should be used solely by the persona select API which is also
        accessed by less privileged accounts. The frontend takes the
        necessary precautions.
        """
        query = affirm(Query, query)
        return self._submit_general_query(rs, query)

    @access("droid_resolve")
    def submit_resolve_api_query(self, rs: RequestState,
                                 query: Query) -> tuple[CdEDBObject, ...]:
        """Accessible version of :py:meth:`submit_general_query`.

        This should be used solely by the resolve API. The frontend takes
        the necessary precautions.
        """
        query = affirm(Query, query)
        return self.general_query(rs, query)

    @access("anonymous")
    def list_email_states(
            self, rs: RequestState,
            states: Optional[Collection[const.EmailStatus]] = None,
    ) -> dict[str, const.EmailStatus]:
        """List all explicit email states known to the CdEDB.

        This is mainly used for handling defect addresses.

        .. note:: This has anonymous access as we send emails in anonymous
                  context (e.g. password reset links). So to be able to do
                  checks during email dispatch this is world-readable (between
                  frontend and backend).

        :param states: Restrict to addresses with one of these states.

        """
        states = affirm_array(const.EmailStatus, states or [])
        query = "SELECT address, status FROM core.email_states"
        params: tuple[Collection[const.EmailStatus], ...] = tuple()
        if states:
            query += " WHERE status = ANY(%s)"
            params += (states,)
        data = self.query_all(rs, query, params)
        return {e['address']: e['status'] for e in data}

    @access("ml")
    def get_defect_address_reports(
            self, rs: RequestState, persona_ids: Optional[Collection[int]] = None,
    ) -> dict[str, EmailAddressReport]:
        # Input validation and permission checks are delegated
        return self.get_email_reports(rs, persona_ids,
                                      const.EmailStatus.defect_states())

    @access("ml")
    def get_email_reports(
            self, rs: RequestState, persona_ids: Optional[Collection[int]] = None,
            stati: Optional[Collection[const.EmailStatus]] = None,
    ) -> dict[str, EmailAddressReport]:
        """Get defect mail addresses and map them to users and mls, if possible.

        :param persona_ids: Retrieve only defect addresses of those users.
        """
        persona_ids = affirm_set(vtypes.ID, persona_ids or set())
        if stati is None:
            stati = tuple(const.EmailStatus)
        stati = affirm_array(const.EmailStatus, stati or [])

        if (not {"ml_admin", "core_admin"} & rs.user.roles
                and persona_ids != {rs.user.persona_id}):
            relative_admin = False
            if len(persona_ids) == 1:
                relative_admin = self.is_relative_admin(rs, unwrap(persona_ids))
            if not relative_admin:
                raise PrivilegeError

        # first, query core.personas
        query = """
            SELECT
                estat.id, estat.address, estat.status, estat.notes,
                core.personas.id AS user_id
            FROM core.email_states AS estat
                LEFT JOIN core.personas ON estat.address = core.personas.username
            WHERE estat.status = ANY(%s)
        """
        params: tuple[Collection[int], ...] = (stati,)
        if persona_ids:
            query += "AND core.personas.id = ANY(%s)"
            params += (persona_ids, )
        data: dict[str, dict[str, Any]] = collections.defaultdict(dict)
        for e in self.query_all(rs, query, params):
            data[e['address']] = e

        # second, query ml.subscription_addresses
        query = """
            SELECT
                estat.id, estat.address, estat.status, estat.notes,
                array_remove(array_agg(sa.mailinglist_id), NULL) AS ml_ids,
                sa.persona_id AS subscriber_id
            FROM core.email_states AS estat
                LEFT JOIN ml.subscription_addresses AS sa ON estat.address = sa.address
            WHERE estat.status = ANY(%s)
        """
        params: tuple[Collection[int], ...] = (stati,)
        if persona_ids:
            query += " AND sa.persona_id = ANY(%s)"
            params += (persona_ids,)
        query += (" GROUP BY estat.id, estat.address, estat.status, estat.notes,"
                  " subscriber_id")
        for e in self.query_all(rs, query, params):
            data[e['address']].update(e)

        ret = EmailAddressReport.many_from_database(data.values())
        return {val.address: val for val in ret.values()}

    @access("core_admin", "ml_admin")
    def mark_email_status(
            self, rs: RequestState, address: str, status: const.EmailStatus,
            notes: Optional[str] = None,
    ) -> DefaultReturnCode:
        address = affirm(vtypes.Email, address)
        status = affirm(const.EmailStatus, status)
        notes = affirm_optional(str, notes)

        with Atomizer(rs):
            code = self.sql_insert(
                rs, EmailAddressReport.database_table,
                {"address": address, "status": status, "notes": notes},
                update_on_conflict=True, conflict_target='address')
            change_note = f"'{address}' als '{status.name}' markiert"
            self.core_log(rs, const.CoreLogCodes.modify_email_status,
                          change_note=change_note)
            return code

    @access("core_admin", "ml_admin")
    def remove_email_status(
            self, rs: RequestState, address: str,
    ) -> DefaultReturnCode:
        address = affirm(vtypes.Email, address)
        with Atomizer(rs):
            change_note = f"'{address}' entfernt"
            self.core_log(rs, const.CoreLogCodes.delete_email_status,
                          change_note=change_note)
            return self.sql_delete_one(rs, EmailAddressReport.database_table,
                                       address, "address")
