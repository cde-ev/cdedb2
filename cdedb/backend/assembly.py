#!/usr/bin/env python3

"""The assembly backend provides ballots.

For reference we describe the technicalities of the voting
process. Every vote is recorded in the table assembly.voter_register,
but only the fact, that the attendee voted; the actual vote goes into
the assembly.votes table. To associate such a vote to an attendee the
attendees voting secret is required. Given a voting secret it is
possible to determine the corresponding vote by bruteforce (this is not
the most performant way, but this way security maintained on a somewhat
higher level). Thus every attendee can update their own vote by
providing their voting secret.

Upon conclusion of the voting period, all votes are tallied and a result
file is produced. This file contains the result as well as all votes. Thus
everybody can verify that their vote was counted correctly and no tampering
has taken place.

Currently all voting secrets are stored in the database and only purged
after the assembly is concluded. However the design is such, that it
would be possible to let the user choose their own voting secrets
without storing it in the database. But the secret would have to be
provided each time the attendee wants to query their current vote or
change it, which has serious usability issues -- thus we currently don't
do it.
"""

import copy
import datetime
import hmac
import math
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Collection, Dict, List, Optional, Protocol, Set, Tuple, Union

from schulze_condorcet import schulze_evaluate

import cdedb.database.constants as const
import cdedb.validationtypes as vtypes
from cdedb.backend.common import (
    AbstractBackend, Silencer, access, affirm_set_validation as affirm_set,
    affirm_validation as affirm, affirm_validation_optional as affirm_optional,
    internal, singularize,
)
from cdedb.common import (
    ASSEMBLY_ATTACHMENT_FIELDS, ASSEMBLY_ATTACHMENT_VERSION_FIELDS,
    ASSEMBLY_BAR_SHORTNAME, ASSEMBLY_FIELDS, BALLOT_FIELDS, CdEDBLog, CdEDBObject,
    CdEDBObjectMap, DefaultReturnCode, DeletionBlockers, EntitySorter, PrivilegeError,
    RequestState, get_hash, glue, implying_realms, json_serialize,
    mixed_existence_sorter, n_, now, unwrap, xsorted,
)
from cdedb.database.connection import Atomizer
from cdedb.query import Query, QueryOperators, QueryScope, QuerySpecEntry


class AssemblyBackend(AbstractBackend):
    """This is an entirely unremarkable backend."""
    realm = "assembly"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.attachment_base_path: Path = (
                self.conf['STORAGE_DIR'] / "assembly_attachment")
        self.ballot_result_base_path: Path = (
                self.conf['STORAGE_DIR'] / 'ballot_result')

    @classmethod
    def is_admin(cls, rs: RequestState) -> bool:
        return super().is_admin(rs)

    def get_attachment_file_path(self, attachment_id: int, version_nr: int) -> Path:
        return self.attachment_base_path / f"{attachment_id}_v{version_nr}"

    def get_ballot_file_path(self, ballot_id: int) -> Path:
        return self.ballot_result_base_path / str(ballot_id)

    @access("assembly")
    def are_assemblies_locked(self, rs: RequestState,
                              assembly_ids: Collection[int]
                              ) -> Dict[int, bool]:
        """Helper to check, whether the assemblies may be modified."""
        assembly_ids = affirm_set(vtypes.ID, assembly_ids)
        q = "SELECT id, is_active FROM assembly.assemblies WHERE id = ANY(%s)"
        params = (assembly_ids, )
        data = self.query_all(rs, q, params)
        return {e["id"]: not e["is_active"] for e in data}

    class _IsAssemblyLockedProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> bool: ...

    is_assembly_locked: _IsAssemblyLockedProtocol = singularize(
        are_assemblies_locked, "assembly_ids", "assembly_id")

    @access("persona")
    def presider_infos(self, rs: RequestState, persona_ids: Collection[int]
                       ) -> Dict[int, Set[int]]:
        """List assemblies managed by specific personas."""
        persona_ids = affirm_set(vtypes.ID, persona_ids)
        data = self.sql_select(
            rs, "assembly.presiders", ("persona_id", "assembly_id"),
            persona_ids, entity_key="persona_id")
        ret = {}
        for anid in persona_ids:
            ret[anid] = {e['assembly_id']
                         for e in data if e['persona_id'] == anid}
        return ret

    class _PresiderInfoProtocol(Protocol):
        def __call__(self, rs: RequestState, persona_id: int
                     ) -> Set[int]: ...
    presider_info: _PresiderInfoProtocol = singularize(
        presider_infos, "persona_ids", "persona_id")

    @access("persona")
    def is_presider(self, rs: RequestState, *, assembly_id: int = None,
                    ballot_id: int = None, attachment_id: int = None,
                    persona_id: int = None) -> bool:
        """Determine if a user has privileged acces to the given assembly.

        If persona_id is not given, the current user is used.
        """
        ballot_id = affirm_optional(vtypes.ID, ballot_id)
        attachment_id = affirm_optional(vtypes.ID, attachment_id)
        if assembly_id is None:
            assembly_id = self.get_assembly_id(
                rs, ballot_id=ballot_id, attachment_id=attachment_id)
        assembly_id = affirm_optional(vtypes.ID, assembly_id)

        if persona_id is None or persona_id == rs.user.persona_id:
            return self.is_admin(rs) or assembly_id in rs.user.presider
        else:
            roles = self.core.get_roles_single(rs, persona_id)
            presiders = self.presider_info(rs, persona_id)
            return "assembly_admin" in roles or assembly_id in presiders

    @internal
    @access("persona")
    def may_access(self, rs: RequestState, *, assembly_id: int = None,
                   ballot_id: int = None, attachment_id: int = None,
                   persona_id: int = None) -> bool:
        """Helper to check authorization.

        The deal is that members may access anything and assembly users
        may access any assembly in which they are participating. This
        especially allows people who have "cde", but not "member" in
        their roles, to access only those assemblies they participated
        in.

        Assembly admins may access every assembly.

        Exactly one of assembly_id and ballot_id has to be provided.

        :param persona_id: If not provided the current user is used.
        """
        persona_id = persona_id or rs.user.persona_id
        roles = self.core.get_roles_single(rs, persona_id)

        if "member" in roles or self.is_presider(
                rs, assembly_id=assembly_id, ballot_id=ballot_id,
                attachment_id=attachment_id, persona_id=persona_id):
            return True
        return self.check_attendance(
            rs, assembly_id=assembly_id, ballot_id=ballot_id,
            attachment_id=attachment_id, persona_id=persona_id)

    @access("persona")
    def may_assemble(self, rs: RequestState, *, assembly_id: int = None,
                     ballot_id: int = None, attachment_id: int = None
                     ) -> bool:
        """Check authorization of this persona.

        This checks, if the calling user may interact with a specific
        assembly or ballot.
        Published variant of 'may_access' with input validation.

        Exactly one of assembly_id, ballot_id and attachment_id has to be
        provided.
        """
        assembly_id = affirm_optional(vtypes.ID, assembly_id)
        ballot_id = affirm_optional(vtypes.ID, ballot_id)
        attachment_id = affirm_optional(vtypes.ID, attachment_id)

        return self.may_access(rs, assembly_id=assembly_id, ballot_id=ballot_id,
                               attachment_id=attachment_id)

    @access("assembly_admin")
    def check_assemble(self, rs: RequestState, persona_id: int, *,
                       assembly_id: int = None, ballot_id: int = None,
                       attachment_id: int = None) -> bool:
        """Check authorization of given persona.

        This checks, if the given persona may interact with a specific
        assembly or ballot.
        Published variant of 'may_access' with input validation.

        Exactly one of assembly_id, ballot_id and attachment_id has to be
        provided.

        :param persona_id: If not provided the current user is used.
        """
        persona_id = affirm_optional(vtypes.ID, persona_id)
        assembly_id = affirm_optional(vtypes.ID, assembly_id)
        ballot_id = affirm_optional(vtypes.ID, ballot_id)
        attachment_id = affirm_optional(vtypes.ID, attachment_id)

        return self.may_access(
            rs, assembly_id=assembly_id, ballot_id=ballot_id,
            persona_id=persona_id, attachment_id=attachment_id)

    @staticmethod
    def encrypt_vote(salt: str, secret: str, vote: str) -> str:
        """Compute a cryptographically secure hash from a vote.

        This hash is used to ensure that only knowledge of the secret
        allows modification of the vote. We use SHA512 as hash.
        """
        h = hmac.new(salt.encode('ascii'), digestmod="sha512")
        h.update(secret.encode('ascii'))
        h.update(vote.encode('ascii'))
        return h.hexdigest()

    def retrieve_vote(self, rs: RequestState, ballot_id: int,
                      secret: str) -> CdEDBObject:
        """Low level function for looking up a vote.

        This is a brute force algorithm checking each vote, whether it
        belongs to the passed secret. This is impossible to do more
        efficiently by design. Otherwise some quality of our voting
        process would be compromised.

        This assumes, that a vote actually exists and throws an error if
        not.
        """
        all_votes = self.sql_select(
            rs, "assembly.votes", ("id", "vote", "salt", "hash"),
            (ballot_id,), entity_key="ballot_id")
        for v in all_votes:
            if v['hash'] == self.encrypt_vote(v['salt'], secret, v['vote']):
                return v
        raise ValueError(n_("No vote found."))

    def assembly_log(self, rs: RequestState, code: const.AssemblyLogCodes,
                     assembly_id: Optional[int],
                     persona_id: Optional[int] = None,
                     change_note: str = None) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param code: One of
          :py:class:`cdedb.database.constants.AssemblyLogCodes`.
        :param persona_id: ID of affected user (like who was subscribed).
        :param change_note: Infos not conveyed by other columns.
        """
        if rs.is_quiet:
            return 0
        # To ensure logging is done if and only if the corresponding action happened,
        # we require atomization here.
        self.affirm_atomized_context(rs)
        # do not use sql_insert since it throws an error for selecting the id
        query = ("INSERT INTO assembly.log (code, assembly_id, submitted_by,"
                 " persona_id, change_note) VALUES (%s, %s, %s, %s, %s)")
        params = (code, assembly_id, rs.user.persona_id, persona_id,
                  change_note)
        return self.query_exec(rs, query, params)

    @access("assembly", "auditor")
    def retrieve_log(self, rs: RequestState,
                     codes: Collection[const.AssemblyLogCodes] = None,
                     assembly_id: int = None, offset: int = None,
                     length: int = None, persona_id: int = None,
                     submitted_by: int = None, change_note: str = None,
                     time_start: datetime.datetime = None,
                     time_stop: datetime.datetime = None) -> CdEDBLog:
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.
        """
        assembly_id = affirm_optional(vtypes.ID, assembly_id)
        if assembly_id is None:
            if not self.is_admin(rs) and "auditor" not in rs.user.roles:
                raise PrivilegeError(n_("Must be admin to access global log."))
            assembly_ids = None
        else:
            if (not self.is_presider(rs, assembly_id=assembly_id)
                    and "auditor" not in rs.user.roles):
                raise PrivilegeError(n_("Must have privileged access to view"
                                        " assembly log."))
            assembly_ids = [assembly_id]
        return self.generic_retrieve_log(
            rs, const.AssemblyLogCodes, "assembly", "assembly.log", codes,
            entity_ids=assembly_ids, offset=offset, length=length,
            persona_id=persona_id, submitted_by=submitted_by,
            change_note=change_note, time_start=time_start,
            time_stop=time_stop)

    @access("core_admin", "assembly_admin")
    def submit_general_query(self, rs: RequestState,
                             query: Query) -> Tuple[CdEDBObject, ...]:
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`
        """
        query = affirm(Query, query)
        if query.scope in {QueryScope.assembly_user, QueryScope.archived_persona}:
            # Include only un-archived assembly-users
            query.constraints.append(("is_assembly_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      query.scope == QueryScope.archived_persona))
            query.spec["is_assembly_realm"] = QuerySpecEntry("bool", "")
            query.spec["is_archived"] = QuerySpecEntry("bool", "")
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('assembly'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = QuerySpecEntry("bool", "")
        else:
            raise RuntimeError(n_("Bad scope."))
        return self.general_query(rs, query)

    @internal
    @access("persona")
    def get_assembly_ids(self, rs: RequestState, *,
                         ballot_ids: Collection[int] = None,
                         attachment_ids: Collection[int] = None
                         ) -> Set[int]:
        """Helper to retrieve a corresponding assembly id."""
        ballot_ids = affirm_set(vtypes.ID, ballot_ids or set())
        attachment_ids = affirm_set(vtypes.ID, attachment_ids or set())
        ret: Set[int] = set()
        if attachment_ids:
            attachment_data = self.sql_select(
                rs, "assembly.attachments", ("assembly_id",), attachment_ids)
            ret.update(e["assembly_id"] for e in attachment_data)
        if ballot_ids:
            ballot_data = self.sql_select(
                rs, "assembly.ballots", ("assembly_id",), ballot_ids)
            ret.update(e["assembly_id"] for e in ballot_data)
        return ret

    @internal
    @access("persona")
    def get_assembly_id(self, rs: RequestState, *, ballot_id: int = None,
                        attachment_id: int = None) -> int:
        """Singular version of `get_assembly_ids`.

        This allows both inputs, but raises an error if they belong to
        different assemblies.

        Providing no inputs or unused ids will also result in an error."""
        if ballot_id is None:
            ballot_ids: Set[int] = set()
        else:
            ballot_ids = {affirm(vtypes.ID, ballot_id)}
        if attachment_id is None:
            attachment_ids: Set[int] = set()
        else:
            attachment_ids = {affirm(vtypes.ID, attachment_id)}
        ret = self.get_assembly_ids(
            rs, ballot_ids=ballot_ids, attachment_ids=attachment_ids)
        if not ret:
            raise ValueError(n_("No input specified."))
        if len(ret) > 1:
            raise ValueError(n_(
                "Can only retrieve id for exactly one assembly."))
        return unwrap(ret)

    @internal
    @access("persona")
    def check_attendance(self, rs: RequestState, *, assembly_id: int = None,
                         ballot_id: int = None, attachment_id: int = None,
                         persona_id: int = None) -> bool:
        """Check whether a persona attends a specific assembly/ballot.

        Exactly one of the inputs assembly_id, ballot_id and attachment_id has
        to be provided.

        This does not check for authorization since it is used during
        the authorization check.

        :param persona_id: If not provided the current user is used.
        """
        inputs = sum(1 for x in (assembly_id, ballot_id, attachment_id) if x)
        if inputs < 1:
            raise ValueError(n_("No input specified."))
        if inputs > 1:
            raise ValueError(n_("Too many inputs specified."))
        if persona_id is None:
            persona_id = rs.user.persona_id

        # Rule out people who can not participate at any assembly to prevent
        # privilege errors
        if persona_id == rs.user.persona_id and "assembly" not in rs.user.roles:
            return False

        # ml_admins are allowed to do this to be able to manage
        # subscribers of assembly mailinglists.
        if not {"assembly", "ml_admin"} | rs.user.roles:
            raise PrivilegeError(n_("Not privileged to access assembly tables"))
        with Atomizer(rs):
            if assembly_id is None:
                assembly_id = self.get_assembly_id(
                    rs, ballot_id=ballot_id, attachment_id=attachment_id)
            query = glue("SELECT id FROM assembly.attendees",
                         "WHERE assembly_id = %s and persona_id = %s")
            return bool(self.query_one(
                rs, query, (assembly_id, persona_id)))

    @access("assembly")
    def does_attend(self, rs: RequestState, *, assembly_id: int = None,
                    ballot_id: int = None) -> bool:
        """Check whether this persona attends a specific assembly/ballot.

        Exactly one of the inputs has to be provided.

        This does not check for authorization since it is used during
        the authorization check.
        """
        assembly_id = affirm_optional(vtypes.ID, assembly_id)
        ballot_id = affirm_optional(vtypes.ID, ballot_id)
        return self.check_attendance(rs, assembly_id=assembly_id,
                                     ballot_id=ballot_id)

    @access("assembly")
    def check_attends(self, rs: RequestState, persona_id: int,
                      assembly_id: int) -> bool:
        """Check whether a user attends an assembly.

        This is mostly used for checking mailinglist eligibility.

        As assembly attendees are public to all assembly users, this does not
        check for any privileges,
        """
        persona_id = affirm(vtypes.ID, persona_id)
        assembly_id = affirm(vtypes.ID, assembly_id)

        return self.check_attendance(
            rs, assembly_id=assembly_id, persona_id=persona_id)

    @access("assembly", "ml_admin")
    def list_attendees(self, rs: RequestState, assembly_id: int
                       ) -> Set[int]:
        """Everybody who has subscribed for a specific assembly.

        This is an unprivileged operation in that everybody (with access
        to the assembly realm) may view this list -- no condition of
        being an attendee. This seems reasonable since assemblies should
        be public to the entire association.

        ml_admins are allowed to do this to be able to manage
        subscribers of assembly mailinglists.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        if not (self.may_access(rs, assembly_id=assembly_id)
                or "ml_admin" in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))
        attendees = self.sql_select(
            rs, "assembly.attendees", ("persona_id",), (assembly_id,),
            entity_key="assembly_id")
        return {e['persona_id'] for e in attendees}

    @access("persona")
    def list_assemblies(self, rs: RequestState,
                        is_active: Optional[bool] = None,
                        restrictive: bool = False) -> CdEDBObjectMap:
        """List all assemblies.

        :param is_active: If not None list only assemblies which have this
          activity status.
        :param restrictive: If true, show only those assemblies the user is
          allowed to interact with.
        :returns: Mapping of event ids to dict with title, activity status and
          signup end. The latter is used to sort the assemblies in index.
        """
        is_active = affirm_optional(bool, is_active)
        query = ("SELECT id, title, signup_end, is_active "
                 "FROM assembly.assemblies")
        constraints = []
        params = []
        if is_active is not None:
            constraints.append("is_active = %s")
            params.append(is_active)
        if constraints:
            query += " WHERE " + " AND ".join(constraints)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e for e in data}
        if restrictive:
            ret = {k: v for k, v in ret.items()
                   if self.may_access(rs, assembly_id=k)}
        return ret

    @access("assembly")
    def get_assemblies(self, rs: RequestState,
                       assembly_ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve data for some assemblies.

        In addition to the keys in `cdedb.common.ASSEMBLY_FIELDS`, this
        retrieves a set of persona ids under the key `'presiders'`, identifying
        those who have privileged access to the assembly (similar to orgas for
        events).
        """
        assembly_ids = affirm_set(vtypes.ID, assembly_ids)
        if not all(self.may_access(rs, assembly_id=anid) for anid in assembly_ids):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, 'assembly.assemblies', ASSEMBLY_FIELDS, assembly_ids)
        presider_data = self.sql_select(
            rs, 'assembly.presiders', ("assembly_id", "persona_id"),
            assembly_ids, entity_key="assembly_id")
        ret = {}
        for assembly in data:
            if 'presiders' in assembly:
                raise RuntimeError(n_("Something went wrong."))
            assembly['presiders'] = {p['persona_id'] for p in presider_data
                                     if p['assembly_id'] == assembly['id']}
            ret[assembly['id']] = assembly
        return ret

    class _GetAssemblyProtocol(Protocol):
        def __call__(self, rs: RequestState, assembly_id: int) -> CdEDBObject: ...
    get_assembly: _GetAssemblyProtocol = singularize(
        get_assemblies, "assembly_ids", "assembly_id")

    @access("assembly")
    def set_assembly(self, rs: RequestState, data: CdEDBObject
                     ) -> DefaultReturnCode:
        """Update some keys of an assembly.

        In addition to the keys in `cdedb.common.ASSEMBLY_FIELDS`, which is
        possible for presiders of this the assembly, this can overwrite the
        set of presiders for the assembly.
        """
        data = affirm(vtypes.Assembly, data)
        if not self.is_presider(rs, assembly_id=data['id']):
            raise PrivilegeError(n_("Must have privileged access to change"
                                    " assembly."))
        ret = 1
        with Atomizer(rs):
            assembly = unwrap(self.get_assemblies(rs, (data['id'],)))
            if not assembly['is_active']:
                raise ValueError(n_("Assembly already concluded."))
            assembly_data = {k: v for k, v in data.items()
                             if k in ASSEMBLY_FIELDS}
            if assembly_data:
                ret *= self.sql_update(rs, "assembly.assemblies", assembly_data)
                self.assembly_log(rs, const.AssemblyLogCodes.assembly_changed,
                                  data['id'])
        return ret

    @access("assembly_admin")
    def add_assembly_presiders(self, rs: RequestState, assembly_id: int,
                               persona_ids: Collection[int]) -> DefaultReturnCode:
        """Add a collection of presiders for an assembly."""
        assembly_id = affirm(vtypes.ID, assembly_id)
        persona_ids = affirm_set(vtypes.ID, persona_ids)

        ret = 1
        with Atomizer(rs):
            assembly = self.get_assembly(rs, assembly_id)
            if not assembly['is_active']:
                raise ValueError(n_("Cannot alter assembly presiders after"
                                    " assembly has been concluded."))
            if not self.core.verify_ids(rs, persona_ids, is_archived=False):
                raise ValueError(n_(
                    "Some of these users do not exist or are archived."))
            if not self.core.verify_personas(rs, persona_ids, {"assembly"}):
                raise ValueError(n_(
                    "Some of these users are not assembly users."))

            for anid in xsorted(persona_ids):
                new_presider = {
                    'persona_id': anid,
                    'assembly_id': assembly_id,
                }
                # on conflict do nothing
                r = self.sql_insert(rs, "assembly.presiders", new_presider,
                                    drop_on_conflict=True)
                if r:
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.assembly_presider_added,
                        assembly_id, anid)
                ret *= r
        return ret

    @access("assembly_admin")
    def remove_assembly_presider(self, rs: RequestState, assembly_id: int,
                                persona_id: int) -> DefaultReturnCode:
        """Remove a single presiders for an assembly."""
        assembly_id = affirm(vtypes.ID, assembly_id)
        persona_id = affirm(vtypes.ID, persona_id)

        query = ("DELETE FROM assembly.presiders"
                 " WHERE persona_id = %s AND assembly_id = %s")
        with Atomizer(rs):
            ret = self.query_exec(rs, query, (persona_id, assembly_id))
            if ret:
                self.assembly_log(rs, const.AssemblyLogCodes.assembly_presider_removed,
                                  assembly_id, persona_id)
        return ret

    @internal
    @access("ml_admin", "assembly")
    def list_assembly_presiders(self, rs: RequestState, assembly_id: int) -> Set[int]:
        """Retrieve a list of assembly presiders.

        This is a helper so that "ml_admin" may retrieve this list even without
        "asembly" realm.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        data = self.sql_select(rs, "assembly.presiders", ("assembly_id", "persona_id"),
                               (assembly_id,), "assembly_id")
        return {e["persona_id"] for e in data}

    @access("assembly_admin")
    def create_assembly(self, rs: RequestState, data: CdEDBObject
                        ) -> DefaultReturnCode:
        """Make a new assembly."""
        data = affirm(vtypes.Assembly, data, creation=True)
        assembly_data = {k: v for k, v in data.items()
                         if k in ASSEMBLY_FIELDS}
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "assembly.assemblies", assembly_data)
            self.assembly_log(
                rs, const.AssemblyLogCodes.assembly_created, new_id)
            if 'presiders' in data:
                self.add_assembly_presiders(rs, new_id, data['presiders'])
        return new_id

    @access("assembly_admin")
    def delete_assembly_blockers(self, rs: RequestState,
                                 assembly_id: int) -> DeletionBlockers:
        """Determine whether an assembly is deletable.

        Possible blockers:

        * assembly_is_locked: Wether the assembly has been locked. In contrast to
                              individual objects linked to the assembly, this does not
                              prevent deletion and cascading of this blocker will also
                              cascade it for the individual objects.
        * ballots: These can have their own blockers like vote_begin.
        * ballot_is_locked: Whether any ballots are locked. Prevents deletion.
        * attendees: Rows of the assembly.attendees table.
        * attachments: All attachments associated with the assembly and it's
                       ballots.
        * presiders: Users with privileged access to this assembly.
        * log: All log entries associated with this assembly.
        * mailinglists: Mailinglists referencing this assembly. The
                        references will be removed, but the lists won't be
                        deleted.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        blockers: DeletionBlockers = {}

        if self.is_assembly_locked(rs, assembly_id):
            blockers["assembly_is_locked"] = [assembly_id]

        ballots = self.sql_select(
            rs, "assembly.ballots", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if ballots:
            blockers["ballots"] = [e["id"] for e in ballots]
            # Take special care with ballots, since they can prevent deletion entirely.
            if self.is_any_ballot_locked(rs, blockers["ballots"]):
                blockers["ballot_is_locked"] = [True]

        attendees = self.sql_select(
            rs, "assembly.attendees", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if attendees:
            blockers["attendees"] = [e["id"] for e in attendees]

        attachments = self.sql_select(
            rs, "assembly.attachments", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if attachments:
            blockers["attachments"] = [e["id"] for e in attachments]

        presiders = self.sql_select(
            rs, "assembly.presiders", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if presiders:
            blockers["presiders"] = [e["id"] for e in presiders]

        log = self.sql_select(
            rs, "assembly.log", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if log:
            blockers["log"] = [e["id"] for e in log]

        mailinglists = self.sql_select(
            rs, "ml.mailinglists", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if mailinglists:
            blockers["mailinglists"] = [e["id"] for e in mailinglists]

        return blockers

    @access("assembly_admin")
    def delete_assembly(self, rs: RequestState, assembly_id: int,
                        cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove an assembly.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        blockers = self.delete_assembly_blockers(rs, assembly_id)
        if "ballot_is_locked" in blockers:
            raise ValueError(n_("Unable to remove active ballot."))
        cascade = affirm_set(str, cascade or set()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "assembly",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            assembly = self.get_assembly(rs, assembly_id)
            if cascade:
                if "assembly_is_locked" in cascade:
                    # Temporarily reactivate the assembly so that it's objects may be
                    # deleted.
                    update = {
                        'id': assembly_id,
                        'is_active': True,
                    }
                    ret *= self.sql_update(rs, "assembly.assemblies", update)
                if "ballots" in cascade:
                    with Silencer(rs):
                        ballot_cascade = ("candidates", "attachment_ballot_links",
                                          "voters")
                        for ballot_id in blockers["ballots"]:
                            ret *= self.delete_ballot(rs, ballot_id, ballot_cascade)
                if "attendees" in cascade:
                    ret *= self.sql_delete(rs, "assembly.attendees",
                                           blockers["attendees"])
                if "attachments" in cascade:
                    with Silencer(rs):
                        attachment_cascade = {"versions", "attachment_ballot_links"}
                        for attachment_id in blockers["attachments"]:
                            ret *= self.delete_attachment(
                                rs, attachment_id, attachment_cascade)
                if "presiders" in cascade:
                    ret *= self.sql_delete(rs, "assembly.presiders",
                                           blockers["presiders"])
                if "log" in cascade:
                    ret *= self.sql_delete(rs, "assembly.log", blockers["log"])
                if "mailinglists" in cascade:
                    for ml_id in blockers["mailinglists"]:
                        deletor = {
                            'assembly_id': None,
                            'id': ml_id,
                        }
                        ret *= self.sql_update(rs, "ml.mailinglists", deletor)

                blockers = self.delete_assembly_blockers(rs, assembly_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "assembly.assemblies", assembly_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.assembly_deleted,
                    assembly_id=None, change_note=assembly["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})

        return ret

    @access("assembly")
    def list_ballots(self, rs: RequestState,
                     assembly_id: int) -> Dict[int, str]:
        """List all ballots of an assembly.

        :returns: Mapping of ballot ids to titles.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        if not self.may_access(rs, assembly_id=assembly_id):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "assembly.ballots", ("id", "title"),
                               (assembly_id,), entity_key="assembly_id")
        return {e['id']: e['title'] for e in data}

    @access("assembly")
    def are_ballots_locked(self, rs: RequestState, ballot_ids: Collection[int]
                           ) -> Dict[int, bool]:
        """Helper to check whether the given ballots may be modified."""
        ballot_ids = affirm_set(vtypes.ID, ballot_ids)
        q = ("SELECT id, vote_begin < %s AS is_locked"
             " FROM assembly.ballots WHERE id = ANY(%s)")
        params = (now(), ballot_ids)
        return {e['id']: e['is_locked'] for e in self.query_all(rs, q, params)}

    class _IsBallotLockedProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> bool: ...
    is_ballot_locked: _IsBallotLockedProtocol = singularize(
        are_ballots_locked, "ballot_ids", "ballot_id")

    @access("assembly")
    def is_any_ballot_locked(self, rs: RequestState, ballot_ids: Collection[int]
                             ) -> bool:
        """Helper to check whether the given ballots may all be modified.

        :returns: True if any of the ballots may not be edited.
        """
        ballot_ids = affirm_set(vtypes.ID, ballot_ids)
        return any(lock for lock in self.are_ballots_locked(rs, ballot_ids).values())

    @access("assembly")
    def are_ballots_voting(self, rs: RequestState, ballot_ids: Collection[int]
                           ) -> Dict[int, bool]:
        """Helper to check whether the given ballots are (partially) open for voting.

        This uses non-obvious logic to catch some edge cases, since extended is None
        until  check_voting_period_extension  is called.

        :returns: True if any of the given ballots is open for voting.
        """
        ballot_ids = affirm_set(vtypes.ID, ballot_ids)
        # This conditional looks complicated since extended may be None and
        # (True/False = None) = None.
        # Therefore, this returns None iff the ballot has not been checked for extension
        # yet, but is between vote_end and vote_extension_end.
        # The third part of the statement makes sure this returns False instead of None
        # if the ballot is definitely over.
        q = """SELECT id, (
            vote_begin < %s
            AND (vote_end > %s OR (vote_extension_end > %s AND extended = True))
            AND NOT COALESCE(vote_extension_end, vote_end) < %s
            ) AS is_voting
        FROM assembly.ballots WHERE id = ANY(%s)"""
        reference_time = now()
        params = (reference_time, reference_time, reference_time, reference_time,
                  ballot_ids)

        # If is_voting is no bool, the voting period extension has not been checked yet.
        # The result of this check equals whether the ballot is still voting.
        with Atomizer(rs):
            return {e["id"]: e['is_voting'] if e['is_voting'] is not None
                    else self.check_voting_period_extension(rs, e["id"])
                    for e in self.query_all(rs, q, params)}

    class _IsBallotVotingProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> bool: ...
    is_ballot_voting: _IsBallotVotingProtocol = singularize(
        are_ballots_voting, "ballot_ids", "ballot_id")

    @access("assembly")
    def is_ballot_concluded(self, rs: RequestState, ballot_id: int) -> bool:
        """Helper to check whether the given ballot has been concluded."""
        with Atomizer(rs):
            return (self.is_ballot_locked(rs, ballot_id)
                and not self.is_ballot_voting(rs, ballot_id))

    @access("assembly")
    def get_ballots(self, rs: RequestState, ballot_ids: Collection[int], *,
                    include_is_voting: bool = True) -> CdEDBObjectMap:
        """Retrieve data for some ballots,

        They do not need to be associated to the same assembly. This has an
        additional field 'candidates' listing the available candidates for
        this ballot.

        If the regular voting period has not yet passed the stored value for `quorum`
        will be `None` and the correct value will be calculated on the fly here.
        Once regular voting ends, the quorum value at that point will be stored and
        afterwards this specific value will be used from there on.

        :param include_is_voting: If False, do not include is_voting key to prevent
            infinite recursions.
        """
        ballot_ids = affirm_set(vtypes.ID, ballot_ids)
        timestamp = now()

        with Atomizer(rs):
            data = self.sql_select(rs, "assembly.ballots", BALLOT_FIELDS + ('comment',),
                                   ballot_ids)
            if include_is_voting:
                are_voting = self.are_ballots_voting(rs, ballot_ids)
            ret = {}
            for e in data:
                if e["quorum"] is None:
                    if e["abs_quorum"]:
                        e["quorum"] = e["abs_quorum"]
                    elif e["rel_quorum"]:
                        # The total number of possible voters is the number of
                        # attendees plus the number of member who may decide to
                        # attend in the future.
                        attendees = self.list_attendees(rs, e["assembly_id"])
                        query = ("SELECT COUNT(id) FROM core.personas"
                                 " WHERE is_member = TRUE AND NOT(id = ANY(%s))")
                        non_attending_member_count = unwrap(
                            self.query_one(rs, query, (attendees,)))
                        assert non_attending_member_count is not None
                        total_count = non_attending_member_count + len(attendees)
                        e["quorum"] = math.ceil(total_count * e["rel_quorum"] / 100)
                    else:
                        e["quorum"] = 0
                e["is_locked"] = timestamp > e["vote_begin"]
                if include_is_voting:
                    e["is_voting"] = are_voting[e["id"]]
                ret[e['id']] = e
            data = self.sql_select(
                rs, "assembly.candidates",
                ("id", "ballot_id", "title", "shortname"), ballot_ids,
                entity_key="ballot_id")
            for anid in ballot_ids:
                candidates = {e['id']: e for e in data
                              if e['ballot_id'] == anid}
                if 'candidates' in ret[anid]:
                    raise RuntimeError()
                ret[anid]['candidates'] = candidates
            ret = {k: v for k, v in ret.items()
                   if self.may_access(rs, ballot_id=k)}
        return ret

    class _GetBallotProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> CdEDBObject: ...
    get_ballot: _GetBallotProtocol = singularize(get_ballots, "ballot_ids", "ballot_id")

    @access("assembly")
    def set_ballot(self, rs: RequestState, data: CdEDBObject) -> DefaultReturnCode:
        """Update some keys of ballot.

        If the key 'candidates' is present, the associated dict mapping the
        candidate ids to the respective data sets can contain an arbitrary
        number of entities, absent entities are not modified.

        Any valid candidate id that is present has to map to a (partial
        or complete) data set or ``None``. In the first case the
        candidate is updated, in the second case it is deleted (this is
        always possible).

        Any invalid candidate id (that is negative integer) has to map to a
        complete data set which will be used to create a new candidate.

        .. note:: It is forbidden to modify a ballot after voting has
          started. In contrast, the comment can not be set here, but only after
          the ballot has ended using `comment_concluded_ballot`.
        """
        data = affirm(vtypes.Ballot, data)
        ret = 1
        with Atomizer(rs):
            current = self.get_ballot(rs, data['id'])
            if not self.is_presider(rs, assembly_id=current['assembly_id']):
                raise PrivilegeError(n_("Must have privileged access to change"
                                        " ballot."))
            if current['is_locked']:
                raise ValueError(n_("Unable to modify active ballot."))
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            if len(bdata) > 1:
                ret *= self.sql_update(rs, "assembly.ballots", bdata)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_changed,
                    current['assembly_id'], change_note=current['title'])
            if 'candidates' in data:
                existing = set(current['candidates'].keys())
                if not (existing >= {x for x in data['candidates'] if x > 0}):
                    raise ValueError(n_("Non-existing candidates specified."))
                new = {x for x in data['candidates'] if x < 0}
                updated = {x for x in data['candidates']
                           if x > 0 and data['candidates'][x] is not None}
                deleted = {x for x in data['candidates']
                           if x > 0 and data['candidates'][x] is None}

                # Defer check of shortname uniqueness until later.
                self.sql_defer_constraints(
                    rs, "assembly.candidate_shortname_constraint")

                # new
                for x in mixed_existence_sorter(new):
                    new_candidate = copy.deepcopy(data['candidates'][x])
                    new_candidate['ballot_id'] = data['id']
                    ret *= self.sql_insert(rs, "assembly.candidates",
                                           new_candidate)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_added,
                        current['assembly_id'],
                        change_note=data['candidates'][x]['shortname'])
                # updated
                for x in mixed_existence_sorter(updated):
                    update = copy.deepcopy(data['candidates'][x])
                    update['id'] = x
                    ret *= self.sql_update(rs, "assembly.candidates", update)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_updated,
                        current['assembly_id'],
                        change_note=current['candidates'][x]['shortname'])
                # deleted
                if deleted:
                    ret *= self.sql_delete(rs, "assembly.candidates", deleted)
                    for x in mixed_existence_sorter(deleted):
                        self.assembly_log(
                            rs, const.AssemblyLogCodes.candidate_removed,
                            current['assembly_id'],
                            change_note=current['candidates'][x]['shortname'])
        return ret

    @access("assembly")
    def create_ballot(self, rs: RequestState, data: CdEDBObject) -> int:
        """Make a new ballot

        This has to take care to keep the voter register consistent.

        :returns: the id of the new ballot
        """
        data = affirm(vtypes.Ballot, data, creation=True)

        with Atomizer(rs):
            if not self.is_presider(rs, assembly_id=data['assembly_id']):
                raise PrivilegeError(n_("Must have privileged access to create"
                                        " ballot."))
            assembly = unwrap(
                self.get_assemblies(rs, (data['assembly_id'],)))
            if not assembly['is_active']:
                raise ValueError(n_("Assembly already concluded."))
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            new_id = self.sql_insert(rs, "assembly.ballots", bdata)
            if new_id <= 0:  # pragma: no cover
                raise RuntimeError(n_("Ballot creation failed."))
            self.assembly_log(rs, const.AssemblyLogCodes.ballot_created,
                              data['assembly_id'], change_note=data['title'])
            if 'candidates' in data:
                cdata = {
                    'id': new_id,
                    'candidates': data['candidates'],
                }
                self.set_ballot(rs, cdata)
            # update voter register
            attendees = self.sql_select(
                rs, "assembly.attendees", ("persona_id",),
                (data['assembly_id'],), entity_key="assembly_id")
            for attendee in attendees:
                entry = {
                    'persona_id': unwrap(attendee),
                    'ballot_id': new_id,
                }
                self.sql_insert(rs, "assembly.voter_register", entry)
        return new_id

    @access("assembly")
    def comment_concluded_ballot(self, rs: RequestState, ballot_id: int,
                                 comment: str = None) -> DefaultReturnCode:
        """Add a comment to a concluded ballot.

        This is intended to note comments regarding tallying, for exmaple tie breakers
        or special preferential votes.

        It is the only operation on a ballot allowed after it has started, and it is
        only allowed after it has ended.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        comment = affirm_optional(str, comment)

        if not self.is_presider(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Must have privileged access to comment ballot."))

        with Atomizer(rs):
            if not self.is_ballot_concluded(rs, ballot_id):
                raise ValueError(n_("Comments are only allowed for concluded ballots."))
            # TODO Check whether assembly has been archived.
            # For now, we would like to use this to clean up archived assmblies.
            current = self.get_ballot(rs, ballot_id)
            data = {'id': ballot_id, 'comment': comment}
            ret = self.sql_update(rs, "assembly.ballots", data)
            self.assembly_log(
                rs, const.AssemblyLogCodes.ballot_changed,
                current['assembly_id'], change_note=current['title'])
        return ret

    @access("assembly")
    def delete_ballot_blockers(self, rs: RequestState,
                               ballot_id: int) -> DeletionBlockers:
        """Determine whether a ballot is deletable.

        Possible blockers:

        * ballot_is_locked: Whether the ballot is locked. Prevents deletion.
        * candidates: Rows in the assembly.candidates table.
        * assembly_is_locked: Whether the assembly is locked. Prevents deletion.
        * attachments: All attachments associated with this ballot.
        * voters: Rows in the assembly.voters table. These do not actually
                  mean that anyone has voted for that ballot, as they are
                  created upon assembly signup and/or ballot creation.
        * votes: Votes that have been cast in this ballot. Prevents deletion.

        :returns: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        blockers: CdEDBObject = {}

        if not self.is_presider(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_(
                "Must have privileged access to delete ballot."))

        ballot = self.get_ballot(rs, ballot_id)
        if ballot['is_locked']:
            blockers['ballot_is_locked'] = [ballot_id]
        if ballot['candidates']:
            blockers['candidates'] = list(ballot['candidates'])

        if self.is_assembly_locked(rs, ballot['assembly_id']):
            blockers['assembly_is_locked'] = [ballot['assembly_id']]

        attachment_ids = self.list_attachments(rs, ballot_id=ballot_id)
        if attachment_ids:
            blockers["attachments"] = attachment_ids

        # Voters are people who _may_ vote in this ballot.
        voters = self.sql_select(rs, "assembly.voter_register", ("id", ),
                                 (ballot_id,), entity_key="ballot_id")
        if voters:
            # Ballot still has voters
            blockers["voters"] = [e["id"] for e in voters]

        # Votes are people who _have_ voted in this ballot.
        votes = self.sql_select(rs, "assembly.votes", ("id",),
                                (ballot_id,), entity_key="ballot_id")
        if votes:
            blockers["votes"] = [e["id"] for e in votes]

        return blockers

    @access("assembly")
    def delete_ballot(self, rs: RequestState, ballot_id: int,
                      cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove a ballot.

        .. note:: As with modification of ballots this is forbidden
          after voting has started.

        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        blockers = self.delete_ballot_blockers(rs, ballot_id)
        if "ballot_is_locked" in blockers:
            raise ValueError(n_("Cannot delete ballot once it has been locked."))
        if "assembly_is_locked" in blockers:
            raise ValueError(n_(
                "Cannot delete ballot once the assembly has been locked."))
        if "votes" in blockers:
            raise ValueError(n_("Cannot delete ballot that has votes."))
        cascade = affirm_set(str, cascade or set()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "ballot",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            current = self.get_ballot(rs, ballot_id)
            if not self.is_presider(rs, assembly_id=current['assembly_id']):
                raise PrivilegeError(n_("Must have privileged access to delete"
                                        " ballot."))
            # cascade specified blockers
            if cascade:
                if "candidates" in cascade:
                    ret *= self.sql_delete(
                        rs, "assembly.candidates", blockers["candidates"])
                if "attachments" in cascade:
                    with Silencer(rs):
                        for attachment_id in blockers["attachments"]:
                            ret *= self.remove_attachment_ballot_link(
                                rs, attachment_id, ballot_id)
                if "voters" in cascade:
                    ret *= self.sql_delete(
                        rs, "assembly.voter_register", blockers["voters"])

                # check if ballot is deletable after maybe cascading
                blockers = self.delete_ballot_blockers(rs, ballot_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "assembly.ballots", ballot_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_deleted,
                    current['assembly_id'], change_note=current['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "ballot", "block": blockers.keys()})
        return ret

    @access("assembly")
    def check_voting_period_extension(self, rs: RequestState, ballot_id: int) -> bool:
        """Update extension status w.r.t. quorum.

        After the normal voting period has ended an extension is enacted
        if the quorum is not met. The quorum may be zero in which case
        it is automatically met.

        This is an unprivileged operation so it can be done
        automatically by everybody when viewing a ballot. It is not
        allowed to call this before the normal voting period has
        expired.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,), include_is_voting=False))
            if ballot['extended'] is not None:
                return ballot['extended']
            if now() < ballot['vote_end']:
                raise ValueError(n_("Normal voting still going on."))
            votes = self.sql_select(rs, "assembly.votes", ("id",),
                                    (ballot_id,), entity_key="ballot_id")
            update = {
                'id': ballot_id,
                'extended': len(votes) < ballot['quorum'],
                'quorum': ballot['quorum'],
            }
            # do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            if update['extended']:
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_extended,
                    ballot['assembly_id'], change_note=ballot['title'])
        return update['extended']

    def process_signup(self, rs: RequestState, assembly_id: int,
                       persona_id: int) -> Union[str, None]:
        """Helper to perform the actual signup

        This has to take care to keep the voter register consistent.

        :returns: The secret if a new secret was generated or None if we
          already attend.
        """
        with Atomizer(rs):
            if self.check_attendance(rs, assembly_id=assembly_id,
                                     persona_id=persona_id):
                # already signed up
                return None
            assembly = unwrap(self.get_assemblies(rs, (assembly_id,)))
            if now() > assembly['signup_end']:
                raise ValueError(n_("Signup already ended."))

            secret = token_urlsafe(12)
            new_attendee = {
                'assembly_id': assembly_id,
                'persona_id': persona_id,
                'secret': secret,
            }
            self.sql_insert(rs, "assembly.attendees", new_attendee)
            self.assembly_log(rs, const.AssemblyLogCodes.new_attendee,
                              assembly_id, persona_id=persona_id)
            # update voter register
            ballots = self.list_ballots(rs, assembly_id)
            for ballot in ballots:
                entry = {
                    'persona_id': persona_id,
                    'ballot_id': ballot,
                }
                self.sql_insert(rs, "assembly.voter_register", entry)
        return secret

    @access("assembly")
    def external_signup(self, rs: RequestState, assembly_id: int,
                        persona_id: int) -> Union[str, None]:
        """Make a non-member attend an assembly.

        Those are not allowed to subscribe themselves, but must be added
        by an admin/presider. On the other hand we disallow this action for
        members.

        :returns: The secret if a new secret was generated or None if we
            already attend.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        persona_id = affirm(vtypes.ID, persona_id)
        if not self.is_presider(rs, assembly_id=assembly_id):
            raise PrivilegeError(n_("Must have privileged access to add an"
                                    " external assembly participant."))

        roles = self.core.get_roles_single(rs, persona_id)
        if "member" in roles:
            raise ValueError(n_("Not allowed for members."))
        if "assembly" not in roles:
            raise ValueError(n_("Only allowed for assembly users."))

        return self.process_signup(rs, assembly_id, persona_id)

    @access("member")
    def signup(self, rs: RequestState, assembly_id: int) -> Union[str, None]:
        """Attend the assembly.

        This does not accept a persona_id on purpose.

        This has to take care to keep the voter register consistent.

        :returns: The secret if a new secret was generated or None if we
          already attend.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        assert rs.user.persona_id is not None
        return self.process_signup(rs, assembly_id, rs.user.persona_id)

    @access("assembly")
    def vote(self, rs: RequestState, ballot_id: int, vote: str,
             secret: Optional[str]) -> DefaultReturnCode:
        """Submit a vote.

        This does not accept a persona_id on purpose.

        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        secret = affirm_optional(vtypes.PrintableASCII, secret)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            vote = affirm(vtypes.Vote, vote, ballot=ballot)
            if not self.check_attendance(rs, ballot_id=ballot_id):
                raise ValueError(n_("Must attend to vote."))
            if not self.is_ballot_voting(rs, ballot_id):
                raise ValueError(n_("Ballot is not open for voting."))

            query = glue("SELECT has_voted FROM assembly.voter_register",
                         "WHERE ballot_id = %s and persona_id = %s")
            has_voted = unwrap(self.query_one(
                rs, query, (ballot_id, rs.user.persona_id)))
            if secret is None:
                query = glue("SELECT secret FROM assembly.attendees",
                             "WHERE assembly_id = %s and persona_id = %s")
                secret = unwrap(self.query_one(
                    rs, query, (ballot['assembly_id'], rs.user.persona_id)))
                if secret is None:
                    raise ValueError(n_("Could not determine secret."))
            if not has_voted:
                salt = token_urlsafe(12)
                entry = {
                    'ballot_id': ballot_id,
                    'vote': vote,
                    'salt': salt,
                    'hash': self.encrypt_vote(salt, secret, vote)
                }
                ret = self.sql_insert(rs, "assembly.votes", entry)
                query = glue(
                    "UPDATE assembly.voter_register SET has_voted = True",
                    "WHERE ballot_id = %s and persona_id = %s")
                ret *= self.query_exec(rs, query,
                                       (ballot_id, rs.user.persona_id))
            else:
                current = self.retrieve_vote(rs, ballot_id, secret)
                update = {
                    'id': current['id'],
                    'vote': vote,
                    'hash': self.encrypt_vote(current['salt'], secret, vote)
                }
                ret = self.sql_update(rs, "assembly.votes", update)
        return ret

    @access("assembly")
    def has_voted(self, rs: RequestState, ballot_id: int) -> bool:
        """Look up whether the user has voted in a ballot.

        It is only allowed to call this if we attend the ballot.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)

        if not self.check_attendance(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Must attend the ballot."))

        query = glue("SELECT has_voted FROM assembly.voter_register",
                     "WHERE ballot_id = %s and persona_id = %s")
        has_voted = unwrap(
            self.query_one(rs, query, (ballot_id, rs.user.persona_id)))
        return bool(has_voted)

    @access("assembly")
    def count_votes(self, rs: RequestState, ballot_id: int) -> int:
        """Look up how many attendees had already voted in a ballot."""
        ballot_id = affirm(vtypes.ID, ballot_id)

        query = glue("SELECT COUNT(*) AS count FROM assembly.voter_register",
                     "WHERE ballot_id = %s and has_voted = True")
        count_votes = unwrap(self.query_one(rs, query, (ballot_id,))) or 0
        return count_votes

    @access("assembly")
    def get_vote(self, rs: RequestState, ballot_id: int,
                 secret: Union[str, None]) -> Union[str, None]:
        """Look up a vote.

        This does not accept a persona_id on purpose.

        It is only allowed to call this if we attend the ballot.

        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :returns: The vote if we have voted or None otherwise. Note, that
          this also returns None, if the secret has been purged after an
          assembly has concluded.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        secret = affirm_optional(vtypes.PrintableASCII, secret)

        if not self.check_attendance(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Must attend the ballot."))

        with Atomizer(rs):
            has_voted = self.has_voted(rs, ballot_id)
            if not has_voted:
                return None
            if secret is None:
                ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
                query = glue("SELECT secret FROM assembly.attendees",
                             "WHERE assembly_id = %s and persona_id = %s")
                secret = unwrap(self.query_one(
                    rs, query, (ballot['assembly_id'], rs.user.persona_id)))
            if secret is None:
                return None
            vote = self.retrieve_vote(rs, ballot_id, secret)
        return vote['vote']

    @access("assembly")
    def get_ballot_result(self, rs: RequestState,
                          ballot_id: int) -> Optional[bytes]:
        """Retrieve the content of a result file for a ballot.

        Returns None if the ballot is not tallied yet or if the file is missing.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        if not self.may_access(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("May not access result for this ballot."))

        ballot = self.get_ballot(rs, ballot_id)
        if not ballot['is_tallied']:
            return None
        else:
            path = self.get_ballot_file_path(ballot_id)
            if not path.exists():
                # TODO raise an error here?
                self.logger.warning(
                    f"Result file for ballot {ballot_id} not found.")
                return None
            with open(path, 'rb') as f:
                ret = f.read()
            return ret

    @access("assembly")
    def tally_ballot(self, rs: RequestState,
                     ballot_id: int) -> Optional[bytes]:
        """Evaluate the result of a ballot.

        After voting has finished all votes are tallied and a result
        file is produced. This file is then published to guarantee the
        integrity of the voting process. It is a valid json file to
        simplify further handling of it.

        This is an unprivileged operation so it can be done
        automatically by everybody when viewing a ballot. It is not
        allowed to call this before voting has actually ended.

        We use the Schulze method as documented in the schulze_condorcet
        pypi package.

        :returns: The content of the file if a new result file was created,
            otherwise None.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)

        if not self.may_access(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            if ballot['is_tallied']:
                return None
            elif now() < ballot['vote_begin']:
                raise ValueError(n_("This ballot has not yet begun."))
            elif self.is_ballot_voting(rs, ballot_id):
                raise ValueError(n_("Voting is still going on."))

            votes = self.sql_select(
                rs, "assembly.votes", ("vote", "salt", "hash"), (ballot_id,),
                entity_key="ballot_id")
            shortnames = tuple(
                x['shortname'] for x in ballot['candidates'].values())
            if ballot['use_bar'] or ballot['votes']:
                shortnames += (ASSEMBLY_BAR_SHORTNAME,)
            vote_result = schulze_evaluate([e['vote'] for e in votes], shortnames)
            update = {
                'id': ballot_id,
                'is_tallied': True,
            }
            # do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            self.assembly_log(
                rs, const.AssemblyLogCodes.ballot_tallied,
                ballot['assembly_id'], change_note=ballot['title'])

            # now generate the result file
            assembly = unwrap(
                self.get_assemblies(rs, (ballot['assembly_id'],)))
            candidates = {
                c['shortname']: c['title']
                for c in xsorted(ballot['candidates'].values(),
                                 key=EntitySorter.candidates)
            }
            query = glue("SELECT persona_id FROM assembly.voter_register",
                         "WHERE ballot_id = %s and has_voted = True")
            voter_ids = self.query_all(rs, query, (ballot_id,))
            voters = self.core.get_personas(
                rs, tuple(unwrap(e) for e in voter_ids))
            voter_names = list(f"{e['given_names']} {e['family_name']}"
                               for e in xsorted(voters.values(),
                                                key=EntitySorter.persona))
            vote_list = xsorted(votes, key=json_serialize)
            result = {
                "assembly": assembly['title'],
                "ballot": ballot['title'],
                "result": vote_result,
                "candidates": candidates,
                "use_bar": ballot['use_bar'],
                "voters": voter_names,
                "votes": vote_list,
            }
            path = self.get_ballot_file_path(ballot_id)
            data = json_serialize(result)
            with open(path, 'w') as f:
                f.write(data)
        ret = data.encode()
        return ret

    @access("assembly_admin")
    def conclude_assembly_blockers(self, rs: RequestState,
                                   assembly_id: int) -> DeletionBlockers:
        """Determine whether an assembly may be concluded.

        Possible blockers:

        * is_active: Only active assemblies may be concluded.
        * signup_end: An Assembly may only be concluded when signup is over.
        * ballot: An Assembly may only be concluded when all ballots are tallied.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        blockers: CdEDBObject = {}

        assembly = self.get_assembly(rs, assembly_id)
        if not assembly['is_active']:
            blockers['is_active'] = [assembly_id]

        timestamp = now()
        if timestamp < assembly['signup_end']:
            blockers["signup_end"] = [assembly['signup_end']]

        ballots = self.sql_select(
            rs, "assembly.ballots", ("id", "is_tallied"), (assembly_id,),
            entity_key="assembly_id")
        for ballot in ballots:
            if not ballot["is_tallied"]:
                if "ballot" not in blockers:
                    blockers["ballot"] = []
                blockers["ballot"].append(ballot["id"])

        return blockers

    @access("assembly_admin")
    def conclude_assembly(self, rs: RequestState, assembly_id: int,
                          cascade: Set[str] = None
                          ) -> DefaultReturnCode:
        """Do housekeeping after an assembly has ended.

        This mainly purges the secrets which are no longer required for
        updating votes, so that they do not leak in the future.

        :param cascade: Specify which conclusion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        """
        assembly_id = affirm(vtypes.ID, assembly_id)
        blockers = self.conclude_assembly_blockers(rs, assembly_id)
        if "is_active" in blockers:
            raise ValueError(n_("Assembly is not active."))
        if "ballot" in blockers:
            raise ValueError(n_("Assembly has open ballots."))
        cascade = affirm_set(str, cascade or set()) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Conclusion of assembly blocked by %(block)s."),
                             {"block": blockers.keys() - cascade})

        ret = 1
        with Atomizer(rs):
            # cascade specified blockers
            if cascade:
                if "signup_end" in cascade:
                    update = {
                        'id': assembly_id,
                        'signup_end': now(),
                    }
                    ret *= self.sql_update(rs, "assembly.assemblies", update)

                blockers = self.conclude_assembly_blockers(rs, assembly_id)

            if not blockers:
                update = {
                    'id': assembly_id,
                    'is_active': False,
                }
                ret *= self.sql_update(rs, "assembly.assemblies", update)
                update = {
                    'assembly_id': assembly_id,
                    'secret': None
                }
                # Don't include in ret, because this may be empty.
                self.sql_update(
                    rs, "assembly.attendees", update, entity_key="assembly_id")
                self.assembly_log(
                    rs, const.AssemblyLogCodes.assembly_concluded, assembly_id)
            else:
                raise ValueError(
                    n_("Conclusion of assembly blocked by %(block)s."),
                    {"block": blockers.keys()})
        return ret

    @internal
    @access("assembly")
    def may_access_attachments(self, rs: RequestState,
                               attachment_ids: Collection[int]) -> bool:
        """Helper to check whether the user may access the given attachments."""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        if not attachment_ids:
            return True
        assembly_ids = self.get_assembly_ids(rs, attachment_ids=attachment_ids)
        if len(assembly_ids) != 1:
            raise ValueError(n_("Can only access attachments from exactly "
                                "one assembly at a time."))
        return self.may_access(rs, assembly_id=unwrap(assembly_ids))

    @access("assembly")
    def add_attachment(self, rs: RequestState, data: CdEDBObject,
                       content: bytes) -> DefaultReturnCode:
        """Add a new attachment.

        Note that it is not allowed to add an attachment to an assembly that has been
        concluded.

        :returns: The id of the new attachment.
        """
        data = affirm(vtypes.AssemblyAttachment, data, creation=True)
        if not self.is_presider(rs, assembly_id=data.get('assembly_id'),
                                ballot_id=data.get('ballot_id')):
            raise PrivilegeError(n_("Must have privileged access to add"
                                    " attachment."))
        locked_msg = n_("Cannot add attachment once the assembly has been locked.")
        attachment = {k: v for k, v in data.items()
                      if k in ASSEMBLY_ATTACHMENT_FIELDS}
        assembly_id = attachment['assembly_id']
        version = {k: v for k, v in data.items()
                   if k in ASSEMBLY_ATTACHMENT_VERSION_FIELDS}
        version["version_nr"] = 1
        version["ctime"] = now()
        version['file_hash'] = get_hash(content)
        with Atomizer(rs):
            if self.is_assembly_locked(rs, assembly_id):
                raise ValueError(locked_msg)
            new_id = self.sql_insert(rs, "assembly.attachments", attachment)
            version['attachment_id'] = new_id
            code = self.sql_insert(rs, "assembly.attachment_versions", version)
            if not code:
                raise RuntimeError(n_("Something went wrong."))
            path = self.get_attachment_file_path(new_id, 1)
            if path.exists():
                raise RuntimeError(n_("File already exists."))
            with open(path, "wb") as f:
                f.write(content)
            self.assembly_log(rs, const.AssemblyLogCodes.attachment_added,
                              assembly_id=assembly_id, change_note=version['title'])
        return new_id

    @access("assembly")
    def delete_attachment_blockers(self, rs: RequestState,
                                   attachment_id: int) -> DeletionBlockers:
        """Determine what keeps an attachment from being deleted.

        Possible blockers:

        * assembly_is_locked: Whether the linked assembly is locked. Prevents deletion.
        * ballots: All linked ballots.
        * ballot_is_locked: Whether a linked ballot is locked. Prevents deletion.
        * versions: All version entries for the attachment including versions,
            that were deleted.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        attachment_id = affirm(vtypes.ID, attachment_id)
        blockers = {}

        attachment = self.get_attachment(rs, attachment_id)
        if self.is_assembly_locked(rs, attachment['assembly_id']):
            blockers['assembly_is_locked'] = [attachment['assembly_id']]
        if attachment['ballot_ids']:
            blockers['ballots'] = attachment['ballot_ids']
            if self.is_any_ballot_locked(rs, blockers['ballots']):
                blockers['ballot_is_locked'] = [True]

        versions = self.get_attachment_versions(rs, attachment_id)
        if versions:
            blockers['versions'] = list(versions)

        return blockers

    @access("assembly")
    def delete_attachment(self, rs: RequestState, attachment_id: int,
                          cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove an attachment."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        blockers = self.delete_attachment_blockers(rs, attachment_id)
        if "assembly_is_locked" in blockers:
            raise ValueError(n_(
                "Cannot delete attachment once the assembly has been locked."))
        if "ballot_is_locked" in blockers:
            raise ValueError(n_(
                "Cannot delete attachment once any linked ballot has been locked."))
        cascade = affirm_set(str, cascade or set()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "assembly attachment",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
            current = self.get_attachment(rs, attachment_id)
            latest_version = self.get_latest_attachment_version(rs, attachment_id)
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to delete"
                                        " attachment."))
            if cascade:
                if "ballots" in cascade:
                    with Silencer(rs):
                        for ballot_id in current['ballot_ids']:
                            ret *= self.remove_attachment_ballot_link(
                                rs, attachment_id, ballot_id)
                if "versions" in cascade:
                    ret *= self.sql_delete(rs, "assembly.attachment_versions",
                                           (attachment_id,), "attachment_id")
                    for version_nr in blockers["versions"]:
                        path = self.get_attachment_file_path(attachment_id, version_nr)
                        if path.exists():
                            path.unlink()
                blockers = self.delete_attachment_blockers(rs, attachment_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "assembly.attachments", attachment_id)
                self.assembly_log(rs, const.AssemblyLogCodes.attachment_removed,
                                  assembly_id, change_note=latest_version['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})
        return ret

    @access("assembly")
    def is_attachment_ballot_link_creatable(self, rs: RequestState,
                                            attachment_id: int,
                                            ballot_id: int) -> bool:
        """An attachment_ballot_link may be created if the ballot it links to is before
        its voting phase."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        ballot_id = affirm(vtypes.ID, ballot_id)
        return not self.is_ballot_locked(rs, ballot_id)

    @access("assembly")
    def is_attachment_ballot_link_deletable(self, rs: RequestState,
                                            attachment_id: int,
                                            ballot_id: int) -> bool:
        """An attachment_ballot_link can only be deleted if the ballot it links to is
        before its voting phase."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        ballot_id = affirm(vtypes.ID, ballot_id)
        return not self.is_ballot_locked(rs, ballot_id)

    @access("assembly")
    def are_attachment_ballots_links_deletable(self, rs: RequestState,
                                               attachment_id: int,
                                               ballot_ids: Collection[int]) -> bool:
        attachment_id = affirm(vtypes.ID, attachment_id)
        ballot_ids = affirm_set(vtypes.ID, ballot_ids)
        return not self.is_any_ballot_locked(rs, ballot_ids)

    @access("assembly")
    def add_attachment_ballot_link(self, rs: RequestState, attachment_id: int,
                                   ballot_id: int) -> DefaultReturnCode:
        """Create a new association attachment <-> ballot."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        ballot_id = affirm(vtypes.ID, ballot_id)
        with Atomizer(rs):
            # This checks that attachment and ballot belong to the same assembly.
            assembly_id = self.get_assembly_id(
                rs, attachment_id=attachment_id, ballot_id=ballot_id)
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to add"
                                        " attachment link."))
            if not self.is_attachment_ballot_link_creatable(rs, attachment_id,
                                                            ballot_id):
                raise ValueError(n_(
                    "Cannot link attachment to ballot that has been locked."))
            ret = self.sql_insert(
                rs, "assembly.attachment_ballot_links",
                {'attachment_id': attachment_id, 'ballot_id': ballot_id},
                drop_on_conflict=True)
            if ret:
                version = self.get_latest_attachment_version(rs, attachment_id)
                ballot = self.get_ballot(rs, ballot_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.attachment_ballot_link_created,
                    assembly_id, persona_id=None,
                    change_note=f"{version['title']} ({ballot['title']})")
                return ret
            else:
                return -1

    @access("assembly")
    def remove_attachment_ballot_link(self, rs: RequestState, attachment_id: int,
                                      ballot_id: int) -> DefaultReturnCode:
        """Remove an association between an attachment and a ballot."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        ballot_id = affirm(vtypes.ID, ballot_id)
        with Atomizer(rs):
            # This checks that attachment and ballot belong to the same assembly.
            assembly_id = self.get_assembly_id(
                rs, attachment_id=attachment_id, ballot_id=ballot_id)
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to delete"
                                        " attachment link."))
            if not self.is_attachment_ballot_link_deletable(rs, attachment_id,
                                                            ballot_id):
                raise ValueError(n_("Cannot unlink attachment from ballot"
                                    " that has been locked."))
            query = ("DELETE FROM assembly.attachment_ballot_links"
                     " WHERE attachment_id = %s AND ballot_id = %s")
            ret = self.query_exec(rs, query, (attachment_id, ballot_id))
            if ret:
                version = self.get_latest_attachment_version(rs, attachment_id)
                ballot = self.get_ballot(rs, ballot_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.attachment_ballot_link_deleted,
                    assembly_id, persona_id=None,
                    change_note=f"{version['title']} ({ballot['title']})")
            return ret

    @access("assembly")
    def set_ballot_attachments(self, rs: RequestState, ballot_id: int,
                               attachment_ids: Collection[int]) -> DefaultReturnCode:
        """Set the attachments linked to an assembly.

        This helper takes care about which attachment links are present, to add or
        to remove compared to the attachment links this ballot previously had.
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        with Atomizer(rs):
            ret = 1
            current_attachments = self.list_attachments(rs, ballot_id=ballot_id)
            new_attachments = attachment_ids - current_attachments
            for attachment_id in xsorted(new_attachments):
                ret *= self.add_attachment_ballot_link(
                    rs, attachment_id=attachment_id, ballot_id=ballot_id)
            deleted_attachments = current_attachments - attachment_ids
            for attachment_id in xsorted(deleted_attachments):
                ret *= self.remove_attachment_ballot_link(
                    rs, attachment_id=attachment_id, ballot_id=ballot_id)
            return ret

    @access("assembly")
    def are_attachment_versions_creatable(self, rs: RequestState,
                                          attachment_ids: Collection[int]
                                          ) -> Dict[int, bool]:
        """An attachment_version may be created at any time during an assembly."""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        with Atomizer(rs):
            attachments = self.get_attachments(rs, attachment_ids)
            assembly_ids = self.get_assembly_ids(rs, attachment_ids=attachment_ids)
            are_assemblies_locked = self.are_assemblies_locked(rs, assembly_ids)
            return {attachment_id: not are_assemblies_locked[attachment["assembly_id"]]
                    for attachment_id, attachment in attachments.items()}

    class _IsAttachmentVersionCreatableProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> bool: ...

    is_attachment_version_creatable: _IsAttachmentVersionCreatableProtocol
    is_attachment_version_creatable = singularize(
        are_attachment_versions_creatable, "attachment_ids", "attachment_id")

    @access("assembly")
    def are_attachment_versions_deletable(self, rs: RequestState,
                                          attachment_ids: Collection[int]
                                          ) -> Dict[int, bool]:
        """An attachment_version must not be deleted if its attachment has at least one
        attachment_ballot_link which voting phase had started."""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        with Atomizer(rs):
            attachments = self.get_attachments(rs, attachment_ids)
            assembly_ids = self.get_assembly_ids(rs, attachment_ids=attachment_ids)
            assembly_locks = self.are_assemblies_locked(rs, assembly_ids)
            return {
                att_id: not (
                    assembly_locks[att['assembly_id']]
                    or self.is_any_ballot_locked(rs, att['ballot_ids'])
                ) for att_id, att in attachments.items()}

    class _IsAttachmentVersionDeletableProtocol(Protocol):
        def __call__(self, rs: RequestState, anid: int) -> bool: ...

    is_attachment_version_deletable: _IsAttachmentVersionDeletableProtocol
    is_attachment_version_deletable = singularize(
        are_attachment_versions_deletable, "attachment_ids", "attachment_id")

    @internal
    def _get_latest_attachments_versions(self, rs: RequestState,
                                         attachment_ids: Collection[int],
                                         timestamp: Optional[datetime.datetime] = None,
                                         ) -> CdEDBObjectMap:
        """Helper to get only the latest (non-deleted) version of attachments.

        :param timestamp: If given, retrieve the latest version before then.
        :returns: Dict[attachment_id, version]
        """
        base_query = """SELECT {select_keys}
            FROM (
                SELECT attachment_id, MAX(version_nr) AS version_nr
                FROM assembly.attachment_versions
                WHERE {condition}
                GROUP BY attachment_id
            ) AS max_version
            LEFT OUTER JOIN assembly.attachment_versions AS version_data
            ON max_version.attachment_id = version_data.attachment_id
                AND max_version.version_nr = version_data.version_nr
            WHERE max_version.attachment_id = ANY(%s)"""
        # Be careful here, because the `attachment_ids` param needs to be at the end.
        params: List[Any] = []
        conditions = ["dtime IS NULL"]
        if timestamp:
            conditions.append("ctime < %s")
            params.append(timestamp)
        query = base_query.format(
            select_keys=', '.join(
                f'version_data.{k}' for k in ASSEMBLY_ATTACHMENT_VERSION_FIELDS),
            condition=" AND ".join(conditions))
        data = self.query_all(rs, query, params + [attachment_ids])
        return {e['attachment_id']: e for e in data}

    @access("assembly")
    def get_attachments_versions(self, rs: RequestState,
                                 attachment_ids: Collection[int],
                                 ) -> Dict[int, CdEDBObjectMap]:
        """Retrieve all version information for given attachments."""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        ret: Dict[int, CdEDBObjectMap] = {anid: {} for anid in attachment_ids}
        if not self.may_access_attachments(rs, attachment_ids):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(
            rs, "assembly.attachment_versions",
            ASSEMBLY_ATTACHMENT_VERSION_FIELDS, attachment_ids,
            entity_key="attachment_id")
        for entry in data:
            ret[entry["attachment_id"]][entry["version_nr"]] = entry

        return ret

    class _GetAttachmentVersionsProtocol(Protocol):
        def __call__(self, rs: RequestState, attachment_id: int) -> CdEDBObjectMap: ...
    get_attachment_versions: _GetAttachmentVersionsProtocol = singularize(
        get_attachments_versions, "attachment_ids", "attachment_id")

    @access("assembly")
    def get_latest_attachments_version(self, rs: RequestState,
                                       attachment_ids: Collection[int],
                                       ) -> CdEDBObjectMap:
        """Get the most recent version for the given attachments.

        This is independent from the context in which the attachment is viewed, in
        contrast to `get_definitive_attachments_version`.
        """
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        if not self.may_access_attachments(rs, attachment_ids):
            raise PrivilegeError(n_("Not privileged."))
        return self._get_latest_attachments_versions(rs, attachment_ids)

    class _GetLatestVersionProtocol(Protocol):
        def __call__(self, rs: RequestState, attachment_id: int) -> CdEDBObject: ...
    get_latest_attachment_version: _GetLatestVersionProtocol = singularize(
        get_latest_attachments_version, "attachment_ids", "attachment_id")

    @access("assembly")
    def get_definitive_attachments_version(
            self, rs: RequestState, ballot_id: int) -> CdEDBObjectMap:
        """Get the definitive version of all attachments for a given ballot.

        The definitive version of an attachment depends on the context in which the
        attachment is viewed – specifically the ballot. This contrasts to the latest
        attachment version, which is independent of context.

        Before the voting phase of the ballot has started, the latest attachment
        version is the definitive version of this attachment for this ballot.

        After the voting phase had started, the last attachment version which was
        uploaded before the voting phase started is the definitive version of this
        attachment for this ballot.

        :returns: Dict[attachment_id: version]
        """
        ballot_id = affirm(vtypes.ID, ballot_id)
        with Atomizer(rs):
            # Access check inside `list_attachments`.
            if attachment_ids := self.list_attachments(rs, ballot_id=ballot_id):
                if self.is_ballot_locked(rs, ballot_id):
                    ballot = self.get_ballot(rs, ballot_id)
                    return self._get_latest_attachments_versions(
                        rs, attachment_ids, ballot['vote_begin'])
                else:
                    return self._get_latest_attachments_versions(rs, attachment_ids)
            return {}

    @access("assembly")
    def add_attachment_version(self, rs: RequestState, data: CdEDBObject,
                               content: bytes) -> DefaultReturnCode:
        """Add a new version of an attachment."""
        data = affirm(vtypes.AssemblyAttachmentVersion, data)
        content = affirm(bytes, content)
        attachment_id = data['attachment_id']
        with Atomizer(rs):
            if not self.is_attachment_version_creatable(rs, attachment_id):
                raise ValueError(n_("Cannot add attachment version once the assembly"
                                    " has been locked."))
            # Take care to include deleted attachment versions here
            query = ("SELECT MAX(version_nr) AS max_version_nr"
                     " FROM assembly.attachment_versions WHERE attachment_id = %s")
            max_version = self.query_one(rs, query, (attachment_id, ))
            if max_version is None:
                raise ValueError(n_("Attachment does not exist."))
            version_nr = max_version["max_version_nr"] + 1
            data['version_nr'] = version_nr
            data['ctime'] = now()
            data['file_hash'] = get_hash(content)
            ret = self.sql_insert(rs, "assembly.attachment_versions", data)
            path = self.get_attachment_file_path(attachment_id, version_nr)
            if path.exists():
                raise ValueError(n_("File already exists."))
            with open(path, "wb") as f:
                f.write(content)
            assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to add"
                                        " attachment version."))
            self.assembly_log(
                rs, const.AssemblyLogCodes.attachment_version_added,
                assembly_id, change_note=f"{data['title']}: Version {version_nr}")
        return ret

    @access("assembly")
    def remove_attachment_version(self, rs: RequestState, attachment_id: int,
                                  version_nr: int) -> DefaultReturnCode:
        """Remove a version of an attachment. Leaves other versions intact."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        version_nr = affirm(vtypes.ID, version_nr)
        with Atomizer(rs):
            if not self.is_presider(rs, attachment_id=attachment_id):
                raise PrivilegeError(n_("Must have privileged access to remove"
                                        " attachment version."))
            if not self.is_attachment_version_deletable(rs, attachment_id):
                raise ValueError(n_(
                    "Cannot remove attachment version once the assembly or"
                    " any linked ballots have been locked."))
            versions = self.get_attachment_versions(rs, attachment_id)
            if version_nr not in versions:
                raise ValueError(n_("This version does not exist."))
            if versions[version_nr]['dtime']:
                raise ValueError(n_("This version has already been deleted."))
            attachment = self.get_attachment(rs, attachment_id)
            if attachment['num_versions'] <= 1:
                raise ValueError(n_("Cannot remove the last remaining version"
                                    " of an attachment."))
            deletor: Dict[str, Union[int, datetime.datetime, None]] = {
                'attachment_id': attachment_id,
                'version_nr': version_nr,
                'dtime': now(),
                'title': None,
                'authors': None,
                'filename': None,
            }

            keys = tuple(deletor.keys())
            setters = ", ".join(f"{k} = %s" for k in keys)
            query = (f"UPDATE assembly.attachment_versions SET {setters}"
                     f" WHERE attachment_id = %s AND version_nr = %s")
            params = tuple(deletor[k] for k in keys) + (attachment_id, version_nr)
            ret = self.query_exec(rs, query, params)

            if ret:
                path = self.get_attachment_file_path(attachment_id, version_nr)
                if path.exists():
                    path.unlink()
                assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
                change_note = f"{versions[version_nr]['title']}: Version {version_nr}"
                self.assembly_log(
                    rs, const.AssemblyLogCodes.attachment_version_removed,
                    assembly_id, change_note=change_note)
        return ret

    @access("assembly")
    def get_attachment_content(self, rs: RequestState, attachment_id: int,
                               version_nr: int = None) -> Union[bytes, None]:
        """Get the content of an attachment. Defaults to most recent version."""
        attachment_id = affirm(vtypes.ID, attachment_id)
        if not self.may_access_attachments(rs, (attachment_id,)):
            raise PrivilegeError(n_("Not privileged."))
        version_nr = affirm_optional(vtypes.ID, version_nr)
        if version_nr is None:
            latest_version = self.get_latest_attachment_version(rs, attachment_id)
            version_nr = latest_version["version_nr"]
        path = self.get_attachment_file_path(attachment_id, version_nr)
        if path.exists():
            with open(path, "rb") as f:
                return f.read()
        return None

    @access("assembly")
    def list_attachments(self, rs: RequestState, *, assembly_id: int = None,
                         ballot_id: int = None) -> Set[int]:
        """List all files attached to an assembly/ballot.

        Exactly one of the inputs has to be provided.
        """
        if assembly_id is None and ballot_id is None:
            raise ValueError(n_("No input specified."))
        if assembly_id is not None and ballot_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        assembly_id = affirm_optional(vtypes.ID, assembly_id)
        ballot_id = affirm_optional(vtypes.ID, ballot_id)
        if not self.may_access(rs, assembly_id=assembly_id, ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        if assembly_id is not None:
            data = self.sql_select(rs, "assembly.attachments", ("id",),
                                   (assembly_id,), entity_key="assembly_id")
        else:
            assert ballot_id is not None
            data = self.sql_select(rs, "assembly.attachment_ballot_links",
                                   ("attachment_id",), (ballot_id,), "ballot_id")

        return {unwrap(e) for e in data}

    def _get_attachment_infos(self, rs: RequestState,
                              attachment_ids: Collection[int]
                              ) -> CdEDBObjectMap:
        """Internal helper to retrieve attachment data without access check."""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        query = f"""SELECT
                {', '.join(ASSEMBLY_ATTACHMENT_FIELDS +
                           ('num_versions', 'latest_version_nr',
                            'COALESCE(ballot_ids, array[]::integer[]) AS ballot_ids'))}
            FROM (
                (
                    SELECT {', '.join(ASSEMBLY_ATTACHMENT_FIELDS)}
                    FROM assembly.attachments
                    WHERE id = ANY(%s)
                ) AS attachments
                LEFT OUTER JOIN (
                    SELECT
                        attachment_id, COUNT(version_nr) as num_versions,
                        MAX(version_nr) as latest_version_nr
                    FROM assembly.attachment_versions
                    WHERE dtime IS NULL
                    GROUP BY attachment_id
                ) AS count ON attachments.id = count.attachment_id
                LEFT OUTER JOIN (
                    SELECT
                        attachment_id,
                        array_agg(ballot_id ORDER BY ballot_id) AS ballot_ids
                    FROM assembly.attachment_ballot_links
                    GROUP BY attachment_id
                ) AS ballot_links ON attachments.id = ballot_links.attachment_id
            )"""
        params = (attachment_ids,)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e for e in data}
        return ret

    @access("assembly")
    def get_attachments(self, rs: RequestState,
                        attachment_ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve data on attachments"""
        attachment_ids = affirm_set(vtypes.ID, attachment_ids)
        if not self.may_access_attachments(rs, attachment_ids):
            raise PrivilegeError(n_("Not privileged."))
        return self._get_attachment_infos(rs, attachment_ids)

    class _GetAttachmentProtocol(Protocol):
        def __call__(self, rs: RequestState, attachment_id: int) -> CdEDBObject: ...
    get_attachment: _GetAttachmentProtocol = singularize(
        get_attachments, "attachment_ids", "attachment_id")
