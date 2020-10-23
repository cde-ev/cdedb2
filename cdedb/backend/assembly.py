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
import hmac
import datetime
from pathlib import Path
from secrets import token_urlsafe

from typing import (
    Any, Set, Dict, Tuple, Union, Callable, Collection, Optional
)
from typing_extensions import Protocol

from cdedb.backend.common import (
    access, affirm_validation as affirm, affirm_set_validation as affirm_set,
    Silencer, singularize, AbstractBackend, internal)
from cdedb.common import (
    n_, glue, unwrap, ASSEMBLY_FIELDS, BALLOT_FIELDS, FUTURE_TIMESTAMP, now,
    ASSEMBLY_ATTACHMENT_FIELDS, schulze_evaluate, EntitySorter,
    PrivilegeError, ASSEMBLY_BAR_SHORTNAME, json_serialize,
    implying_realms, xsorted, RequestState, ASSEMBLY_ATTACHMENT_VERSION_FIELDS,
    get_hash, mixed_existence_sorter, CdEDBObject, CdEDBObjectMap,
    DefaultReturnCode, DeletionBlockers, CdEDBLog,
)
from cdedb.query import QueryOperators, Query
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const


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

    @access("persona")
    def presider_infos(self, rs: RequestState, ids: Collection[int]
                       ) -> Dict[int, Set[int]]:
        """List assemblies managed by specific personas."""
        ids = affirm_set("id", ids)
        data = self.sql_select(
            rs, "assembly.presiders", ("persona_id", "assembly_id"),
            ids, entity_key="persona_id")
        ret = {}
        for anid in ids:
            ret[anid] = {e['assembly_id']
                         for e in data if e['persona_id'] == anid}
        return ret
    presider_info: Callable[['AssemblyBackend', RequestState, int], Set[int]]
    presider_info = singularize(presider_infos)

    @access("persona")
    def is_presider(self, rs: RequestState, *, assembly_id: int = None,
                    ballot_id: int = None, attachment_id: int = None,
                    persona_id: int = None) -> bool:
        """Determine if a user has privileged acces to the given assembly.

        If persona_id is not given, the current user is used.
        """
        ballot_id = affirm("id_or_None", ballot_id)
        attachment_id = affirm("id_or_None", attachment_id)
        if assembly_id is None:
            assembly_id = self.get_assembly_id(
                rs, ballot_id=ballot_id, attachment_id=attachment_id)
        assembly_id = affirm("id", assembly_id)

        if not persona_id:
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
                     ballot_id: int = None, attachment_id: int = None) -> bool:
        """Check authorization of this persona.

        This checks, if the calling user may interact with a specific
        assembly or ballot.
        Published variant of 'may_access' with input validation.

        Exactly one of assembly_id, ballot_id and attachment_id has to be
        provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type ballot_id: int
        :rtype: bool
        """
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
        attachment_id = affirm("id_or_None", attachment_id)

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
        persona_id = affirm("id_or_None", persona_id)
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
        attachment_id = affirm("id_or_None", attachment_id)

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
                     assembly_id: Union[int, None],
                     persona_id: Union[int, None] = None,
                     change_note: str = None) -> DefaultReturnCode:
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :param code: One of
          :py:class:`cdedb.database.constants.AssemblyLogCodes`.
        :param persona_id: ID of affected user (like who was subscribed).
        :param change_note: Infos not conveyed by other columns.
        :returns: default return code
        """
        if rs.is_quiet:
            return 0
        # do not use sql_insert since it throws an error for selecting the id
        query = ("INSERT INTO assembly.log (code, assembly_id, submitted_by,"
                 " persona_id, change_note) VALUES (%s, %s, %s, %s, %s)")
        params = (code, assembly_id, rs.user.persona_id, persona_id,
                  change_note)
        return self.query_exec(rs, query, params)

    @access("assembly")
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
        assembly_id = affirm("id_or_None", assembly_id)
        if assembly_id is None:
            if not self.is_admin(rs):
                raise PrivilegeError(n_("Must be admin to access global log."))
            assembly_ids = None
        else:
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to view"
                                        " assembly log."))
            assembly_ids = [assembly_id]
        return self.generic_retrieve_log(
            rs, "enum_assemblylogcodes", "assembly", "assembly.log", codes,
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
        query = affirm("query", query)
        if query.scope == "qview_persona":
            # Include only un-archived assembly-users
            query.constraints.append(("is_assembly_realm", QueryOperators.equal,
                                      True))
            query.constraints.append(("is_archived", QueryOperators.equal,
                                      False))
            query.spec["is_assembly_realm"] = "bool"
            query.spec["is_archived"] = "bool"
            # Exclude users of any higher realm (implying event)
            for realm in implying_realms('assembly'):
                query.constraints.append(
                    ("is_{}_realm".format(realm), QueryOperators.equal, False))
                query.spec["is_{}_realm".format(realm)] = "bool"
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
        ballot_ids = affirm_set("id", ballot_ids or set())
        attachment_ids = affirm_set("id", attachment_ids or set())
        ret = set()
        if attachment_ids:
            attachment_data = self._get_attachment_infos(rs, attachment_ids)
            for e in attachment_data.values():
                if e["assembly_id"]:
                    ret.add(e["assembly_id"])
                if e["ballot_id"]:
                    ballot_ids.add(e["ballot_id"])
        if ballot_ids:
            ballot_data = self.sql_select(
                rs, "assembly.ballots", ("assembly_id",), ballot_ids)
            for e in ballot_data:
                ret.add(e["assembly_id"])
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
            ballot_ids = {affirm("id", ballot_id)}
        if attachment_id is None:
            attachment_ids: Set[int] = set()
        else:
            attachment_ids = {affirm("id", attachment_id)}
        ret = self.get_assembly_ids(
            rs, ballot_ids=ballot_ids, attachment_ids=attachment_ids)
        if len(ret) == 0:
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
        if (persona_id == rs.user.persona_id and
                "assembly" not in rs.user.roles):
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
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
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
        persona_id = affirm("id", persona_id)
        assembly_id = affirm("id", assembly_id)

        return self.check_attendance(
            rs, assembly_id=assembly_id, persona_id=persona_id)

    @access("assembly", "ml_admin")
    def list_attendees(self, rs: RequestState, assembly_id: int) -> Set[int]:
        """Everybody who has subscribed for a specific assembly.

        This is an unprivileged operation in that everybody (with access
        to the assembly realm) may view this list -- no condition of
        being an attendee. This seems reasonable since assemblies should
        be public to the entire association.

        ml_admins are allowed to do this to be able to manage
        subscribers of assembly mailinglists.
        """
        assembly_id = affirm("id", assembly_id)
        if not (self.may_access(rs, assembly_id=assembly_id)
                or "ml_admin" in rs.user.roles):
            raise PrivilegeError(n_("Not privileged."))
        attendees = self.sql_select(
            rs, "assembly.attendees", ("persona_id",), (assembly_id,),
            entity_key="assembly_id")
        return {e['persona_id'] for e in attendees}

    @access("persona")
    def list_assemblies(self, rs: RequestState,
                        is_active: Union[bool, None] = None,
                        restrictive: bool = False) -> CdEDBObjectMap:
        """List all assemblies.

        :param is_active: If not None list only assemblies which have this
          activity status.
        :param restrictive: If true, show only those assemblies the user is
          allowed to interact with.
        :returns: Mapping of event ids to dict with title, activity status and
          signup end. The latter is used to sort the assemblies in index.
        """
        is_active = affirm("bool_or_None", is_active)
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
                       ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve data for some assemblies.

        In addition to the keys in `cdedb.common.ASSEMBLY_FIELDS`, this
        retrieves a set of persona ids under the key `'presiders'`, identifying
        those who have privileged access to the assembly (similar to orgas for
        events).
        """
        ids = affirm_set("id", ids)
        if not all(self.may_access(rs, assembly_id=anid) for anid in ids):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, 'assembly.assemblies', ASSEMBLY_FIELDS, ids)
        presider_data = self.sql_select(
            rs, 'assembly.presiders', ("assembly_id", "persona_id"),
            ids, entity_key="assembly_id")
        ret = {}
        for assembly in data:
            if 'presiders' in assembly:
                raise RuntimeError(n_("Something went wrong."))
            assembly['presiders'] = {p['persona_id'] for p in presider_data
                                     if p['assembly_id'] == assembly['id']}
            ret[assembly['id']] = assembly
        return ret
    get_assembly: Callable[['AssemblyBackend', RequestState, int], CdEDBObject]
    get_assembly = singularize(get_assemblies)

    @access("assembly")
    def set_assembly(self, rs: RequestState, data: CdEDBObject
                     ) -> DefaultReturnCode:
        """Update some keys of an assembly.

        In addition to the keys in `cdedb.common.ASSEMBLY_FIELDS`, which is
        possible for presiders of this the assembly, this can overwrite the
        set of presiders for the assembly.

        Updating the presiders is delegated to `set_assembly_presiders`, and
        requires admin privileges.
        """
        data = affirm("assembly", data)
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
            if 'presiders' in data:
                ret *= self.set_assembly_presiders(
                    rs, data['id'], data['presiders'])
        return ret

    @access("assembly_admin")
    def set_assembly_presiders(self, rs: RequestState, assembly_id: int,
                               ids: Collection[int]) -> DefaultReturnCode:
        """Overwrite the set of presiders for an assembly."""
        assembly_id = affirm("id", assembly_id)
        ids = affirm_set("id", ids)
        with Atomizer(rs):
            assembly = self.get_assembly(rs, assembly_id)
            if not assembly['is_active']:
                raise ValueError(n_("Cannot alter assembly presiders after"
                                    " assembly has been concluded."))
            if not self.core.verify_ids(rs, ids, is_archived=False):
                raise ValueError(n_(
                    "Some of these users do not exist or are archived."))
            if not self.core.verify_personas(rs, ids, {"assembly"}):
                raise ValueError(n_(
                    "Some of these users are not assembly users."))
            current = self.sql_select(rs, "assembly.presiders", ("persona_id",),
                                      (assembly_id,), entity_key="assembly_id")
            existing = {unwrap(e) for e in current}
            new = ids - existing
            deleted = existing - ids
            ret = 1
            if new:
                inserts = [{
                        'persona_id': anid,
                        'assembly_id': assembly_id,
                } for anid in mixed_existence_sorter(new)]
                ret *= self.sql_insert_many(rs, "assembly.presiders", inserts)
                for anid in mixed_existence_sorter(new):
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.assembly_presider_added,
                        assembly_id, anid)
            if deleted:
                query = ("DELETE FROM assembly.presiders"
                         " WHERE persona_id = ANY(%s) AND assembly_id = %s")
                ret *= self.query_exec(rs, query, (deleted, assembly_id))
                for anid in mixed_existence_sorter(deleted):
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.assembly_presider_removed,
                        assembly_id, anid)
        return ret

    @access("assembly_admin")
    def create_assembly(self, rs: RequestState, data: CdEDBObject
                        ) -> DefaultReturnCode:
        """Make a new assembly."""
        data = affirm("assembly", data, creation=True)
        assembly_data = {k: v for k, v in data.items()
                         if k in ASSEMBLY_FIELDS}
        with Atomizer(rs):
            new_id = self.sql_insert(rs, "assembly.assemblies", assembly_data)
            self.assembly_log(
                rs, const.AssemblyLogCodes.assembly_created, new_id)
            if 'presiders' in data:
                self.set_assembly_presiders(rs, new_id, data['presiders'])
        return new_id

    @access("assembly_admin")
    def delete_assembly_blockers(self, rs: RequestState,
                                 assembly_id: int) -> DeletionBlockers:
        """Determine whether an assembly is deletable.

        Possible blockers:

        * ballots: These can have their own blockers like vote_begin.
        * vote_begin: Ballots where voting has begun. Prevents deletion.
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
        assembly_id = affirm("id", assembly_id)
        blockers = {}

        ballots = self.sql_select(
            rs, "assembly.ballots", ("id",), (assembly_id,),
            entity_key="assembly_id")
        if ballots:
            blockers["ballots"] = [e["id"] for e in ballots]
            for ballot_id in blockers["ballots"]:
                if "vote_begin" in self.delete_ballot_blockers(rs, ballot_id):
                    if "vote_begin" not in blockers:
                        blockers["vote_begin"] = []
                    blockers["vote_begin"].append(ballot_id)

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
        assembly_id = affirm("id", assembly_id)
        blockers = self.delete_assembly_blockers(rs, assembly_id)
        if "vote_begin" in blockers:
            raise ValueError(n_("Unable to remove active ballot."))
        cascade = affirm_set("str", cascade or set()) & blockers.keys()

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
                if "vote_begin" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "vote_begin"})
                if "ballots" in cascade:
                    with Silencer(rs):
                        for ballot_id in blockers["ballots"]:
                            ret *= self.delete_ballot(rs, ballot_id)
                if "attendees" in cascade:
                    ret *= self.sql_delete(rs, "assembly.attendees",
                                           blockers["attendees"])
                if "attachments" in cascade:
                    with Silencer(rs):
                        attachment_cascade = {"versions"}
                        for attachment_id in blockers["attachments"]:
                            ret *= self.delete_attachment(
                                rs, attachment_id, attachment_cascade)
                if "presiders" in cascade:
                    ret *= self.sql_delete(rs, "assembly.presiders",
                                           blockers["presiders"])
                if "log" in cascade:
                    ret *= self.sql_delete(rs, "assembly.log", blockers["log"])
                if "mailinglists" in cascade:
                    for ml_id in blockers["amilinglists"]:
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :rtype: {int: str}
        :returns: Mapping of ballot ids to titles.
        """
        assembly_id = affirm("id", assembly_id)
        if not self.may_access(rs, assembly_id=assembly_id):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "assembly.ballots", ("id", "title"),
                               (assembly_id,), entity_key="assembly_id")
        return {e['id']: e['title'] for e in data}

    @access("assembly")
    def get_ballots(self, rs: RequestState,
                    ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve data for some ballots,

        They do not need to be associated to the same assembly. This has an
        additional field 'candidates' listing the available candidates for
        this ballot.

        If the regular voting period has not yet passed the stored value for `quorum`
        will be `None` and the correct value will be calculated on the fly here.
        Once regular voting ends, the quorum value at that point will be stored and
        afterwards this specific value will be used from there on.
        """
        ids = affirm_set("id", ids)

        with Atomizer(rs):
            data = self.sql_select(rs, "assembly.ballots", BALLOT_FIELDS, ids)
            ret = {}
            for e in data:
                if e["quorum"] is None:
                    if e["abs_quorum"]:
                        e["quorum"] = e["abs_quorum"]
                    elif e["rel_quorum"]:
                        attendees = self.list_attendees(rs, e["assembly_id"])
                        query = ("SELECT COUNT(id) FROM core.personas"
                                 " WHERE is_member = TRUE AND NOT(id = ANY(%s))")
                        member_count = unwrap(self.query_one(rs, query, (attendees,)))
                        total_count = member_count + len(attendees)
                        e["quorum"] = -(-total_count * e["rel_quorum"] // 100)
                ret[e['id']] = e
            data = self.sql_select(
                rs, "assembly.candidates",
                ("id", "ballot_id", "title", "shortname"), ids,
                entity_key="ballot_id")
            for anid in ids:
                candidates = {e['id']: e for e in data
                              if e['ballot_id'] == anid}
                assert ('candidates' not in ret[anid])
                ret[anid]['candidates'] = candidates
            ret = {k: v for k, v in ret.items()
                   if self.may_access(rs, ballot_id=k)}
        return ret
    get_ballot: Callable[['AssemblyBackend', RequestState, int], CdEDBObject]
    get_ballot = singularize(get_ballots)

    @access("assembly")
    def set_ballot(self, rs: RequestState, data: CdEDBObject) -> int:
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
          started.

        :returns: default return code
        """
        data = affirm("ballot", data)
        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_ballots(rs, (data['id'],)))
            if not self.is_presider(rs, assembly_id=current['assembly_id']):
                raise PrivilegeError(n_("Must have privileged access to change"
                                        " ballot."))
            if now() > current['vote_begin']:
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

        :returns: the id of the new event
        """
        data = affirm("ballot", data, creation=True)

        with Atomizer(rs):
            if not self.is_presider(rs, assembly_id=data['assembly_id']):
                raise PrivilegeError(n_("Must have privileged access to create"
                                        " ballot."))
            assembly = unwrap(
                self.get_assemblies(rs, (data['assembly_id'],)))
            if not assembly['is_active']:
                raise ValueError(n_("Assembly already concluded."))
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            # do a little dance, so that creating a running ballot does not
            # throw an error
            begin, bdata['vote_begin'] = bdata['vote_begin'], FUTURE_TIMESTAMP
            new_id = self.sql_insert(rs, "assembly.ballots", bdata)
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
            # fix vote_begin stashed above
            update = {
                'id': new_id,
                'vote_begin': begin,
            }
            self.set_ballot(rs, update)
        self.assembly_log(rs, const.AssemblyLogCodes.ballot_created,
                          data['assembly_id'], change_note=data['title'])
        return new_id

    @access("assembly")
    def delete_ballot_blockers(self, rs: RequestState,
                               ballot_id: int) -> DeletionBlockers:
        """Determine whether a ballot is deletable.

        Possible blockers:

        * vote_begin: Whether voting on the ballot has begun.
                      Prevents deletion.
        * candidates: Rows in the assembly.candidates table.
        * attachments: All attachments associated with this ballot.
        * votes: Votes that have been cast in this ballot. Prevents deletion.
        * voters: Rows in the assembly.voters table. These do not actually
                  mean that anyone has voted for that ballot, as they are
                  created upon assembly signup and/or ballot creation.

        :returns: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        ballot_id = affirm("id", ballot_id)
        blockers = {}

        if not self.is_presider(rs, ballot_id=ballot_id):
            raise RuntimeError(n_(
                "Must have privileged access to delete ballot."))

        # TODO use an Atomizer here?
        ballot = self.get_ballot(rs, ballot_id)
        if now() > ballot['vote_begin']:
            # Unable to remove active ballot
            blockers["vote_begin"] = [ballot_id]
        if ballot['candidates']:
            # Ballot still has candidates
            blockers["candidates"] = [anid for anid in ballot["candidates"]]

        attachments = self.list_attachments(rs, ballot_id=ballot_id)
        if attachments:
            # Ballot still has attachments
            blockers["attachments"] = [anid for anid in attachments]

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
        ballot_id = affirm("id", ballot_id)
        blockers = self.delete_ballot_blockers(rs, ballot_id)
        cascade = affirm_set("str", cascade or set()) & blockers.keys()

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
                if "vote_begin" in cascade:
                    raise ValueError(n_("Cannot delete ballot that has started"
                                        " voting."))
                if "votes" in cascade:
                    raise ValueError(n_("Cannot delete ballot that has votes."))
                if "candidates" in cascade:
                    ret *= self.sql_delete(
                        rs, "assembly.candidates", blockers["candidates"])
                if "attachments" in cascade:
                    with Silencer(rs):
                        attachment_cascade = {"versions"}
                        for attachment_id in blockers["attachments"]:
                            ret *= self.delete_attachment(
                                rs, attachment_id, attachment_cascade)
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
        ballot_id = affirm("id", ballot_id)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
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
        assembly_id = affirm("id", assembly_id)
        persona_id = affirm("id", persona_id)
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
        assembly_id = affirm("id", assembly_id)
        assert rs.user.persona_id is not None
        return self.process_signup(rs, assembly_id, rs.user.persona_id)

    @access("assembly")
    def vote(self, rs: RequestState, ballot_id: int, vote: str,
             secret: Optional[str]) -> DefaultReturnCode:
        """Submit a vote.

        This does not accept a persona_id on purpose.

        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :returns: default return code
        """
        ballot_id = affirm("id", ballot_id)
        secret = affirm("printable_ascii_or_None", secret)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            vote = affirm("vote", vote, ballot=ballot)
            if not self.check_attendance(rs, ballot_id=ballot_id):
                raise ValueError(n_("Must attend to vote."))
            if ballot['extended']:
                reference = ballot['vote_extension_end']
            else:
                reference = ballot['vote_end']
            if now() > reference:
                raise ValueError(n_("Ballot already closed."))
            if now() < ballot['vote_begin']:
                raise ValueError(n_("Ballot not yet open."))

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
        ballot_id = affirm("id", ballot_id)

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
        ballot_id = affirm("id", ballot_id)

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
        ballot_id = affirm("id", ballot_id)
        secret = affirm("printable_ascii_or_None", secret)

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
        ballot_id = affirm("id", ballot_id)
        if not self.may_access(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("May not access result for this ballot."))

        ballot = self.get_ballot(rs, ballot_id)
        if not ballot['is_tallied']:
            return None
        else:
            path = self.ballot_result_base_path / str(ballot_id)
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

        We use the Schulze method as documented in
        :py:func:`cdedb.common.schulze_evaluate`.

        :returns: The content of the file if a new result file was created,
            otherwise None.
        """
        ballot_id = affirm("id", ballot_id)

        if not self.may_access(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            if ballot['is_tallied']:
                return None
            if ballot['extended'] is None:
                raise ValueError(n_("Extension unchecked."))
            if ballot['extended']:
                reference = ballot['vote_extension_end']
            else:
                reference = ballot['vote_end']
            if now() < reference:
                raise ValueError(n_("Voting still going on."))

            votes = self.sql_select(
                rs, "assembly.votes", ("vote", "salt", "hash"), (ballot_id,),
                entity_key="ballot_id")
            shortnames = tuple(
                x['shortname'] for x in ballot['candidates'].values())
            if ballot['use_bar'] or ballot['votes']:
                shortnames += (ASSEMBLY_BAR_SHORTNAME,)
            condensed, detailed = schulze_evaluate([e['vote'] for e in votes],
                                                   shortnames)
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
            vote_list = xsorted(votes, key=lambda v: json_serialize(v))
            result = {
                "assembly": assembly['title'],
                "ballot": ballot['title'],
                "result": condensed,
                "candidates": candidates,
                "use_bar": ballot['use_bar'],
                "voters": voter_names,
                "votes": vote_list,
            }
            path = self.ballot_result_base_path / str(ballot_id)
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
        * ballot: An Assembly may only be concluded when all ballots are
                  tallied.
        """
        assembly_id = affirm("id", assembly_id)
        blockers = {}

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
                          cascade: Set[str] = None) -> int:
        """Do housekeeping after an assembly has ended.

        This mainly purges the secrets which are no longer required for
        updating votes, so that they do not leak in the future.

        :param cascade: Specify which conclusion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :returns: default return code
        """
        assembly_id = affirm("id", assembly_id)
        blockers = self.conclude_assembly_blockers(rs, assembly_id)
        if "is_active" in blockers:
            raise ValueError(n_("Assembly is not active."))
        if "ballot" in blockers:
            raise ValueError(n_("Assembly has open ballots."))
        cascade = affirm_set("str", cascade or set()) & blockers.keys()
        if blockers.keys() - cascade:
            raise ValueError(n_("Conclusion of assembly blocked by %(block)s."),
                             {"block": blockers.keys() - cascade})

        ret = 1
        with Atomizer(rs):
            # cascade specified blockers
            if cascade:
                if "is_active" in cascade:
                    ValueError(n_("Unable to cascade %(blocker)s."),
                               {"blocker": "is_active"})
                if "ballot" in cascade:
                    ValueError(n_("Unable to cascade %(blocker)s."),
                               {"blocker": "ballot"})
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
    def check_attachment_access(self, rs: RequestState,
                                attachment_ids: Collection[int]) -> bool:
        """Helper to check whether the user may access the given attachments."""
        attachment_ids = affirm_set("id", attachment_ids)
        with Atomizer(rs):
            if not attachment_ids:
                return True
            assembly_ids = self.get_assembly_ids(
                rs, attachment_ids=attachment_ids)
            if len(assembly_ids) != 1:
                raise ValueError(n_("Can only access attachments from exactly "
                                    "one assembly at a time."))
            return self.may_access(rs, assembly_id=unwrap(assembly_ids))

    @access("assembly")
    def check_ballot_locked(self, rs: RequestState, ballot_id: int) -> bool:
        """Helper to check, whether a ballot may be modified.

        :returns: True if the ballot may not be edited, False otherwise.
        """
        ballot_id = affirm("id", ballot_id)
        ballot = self.get_ballot(rs, ballot_id)
        return ballot['vote_begin'] < now()

    @access("assembly")
    def check_attachment_locked(self, rs: RequestState,
                                attachment_id: int) -> bool:
        """Helper to check, whether a attachment may be modified.

        :returns: True if the attachment may not be edited, False otherwise.
        """
        attachment_id = affirm("id", attachment_id)
        with Atomizer(rs):
            attachment = self.get_attachment(rs, attachment_id)
            if attachment['ballot_id']:
                if self.check_ballot_locked(rs, attachment['ballot_id']):
                    return True
            assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
            assembly = self.get_assembly(rs, assembly_id)
            return not assembly['is_active']

    @access("assembly")
    def get_attachment_histories(self, rs: RequestState,
                                 attachment_ids: Collection[int]
                                 ) -> Dict[int, CdEDBObjectMap]:
        """Retrieve all version information for given attachments."""
        attachment_ids = affirm_set("id", attachment_ids)
        ret: Dict[int, CdEDBObjectMap] = {anid: {} for anid in attachment_ids}
        with Atomizer(rs):
            if not self.check_attachment_access(rs, attachment_ids):
                raise PrivilegeError(n_("Not privileged."))
            data = self.sql_select(
                rs, "assembly.attachment_versions",
                ASSEMBLY_ATTACHMENT_VERSION_FIELDS, attachment_ids,
                entity_key="attachment_id")
            for entry in data:
                ret[entry["attachment_id"]][entry["version"]] = entry

        return ret
    get_attachment_history: Callable[['AssemblyBackend', RequestState, int],
                                     CdEDBObjectMap]
    get_attachment_history = singularize(
        get_attachment_histories, "attachment_ids", "attachment_id")

    @access("assembly")
    def add_attachment(self, rs: RequestState, data: CdEDBObject,
                       content: bytes) -> DefaultReturnCode:
        """Add a new attachment.

        Note that it is not allowed to add an attachment to a ballot that
        has started voting or to an assembly that has been concluded.

        :returns: The id of the new attachment.
        """
        data = affirm("assembly_attachment", data, creation=True)
        with Atomizer(rs):
            if not self.is_presider(rs, assembly_id=data.get('assembly_id'),
                                    ballot_id=data.get('ballot_id')):
                raise PrivilegeError(n_("Must have privileged access to add"
                                        " attachment."))
            locked_msg = n_("Unable to change attachment once voting has begun"
                            " or the assembly has been concluded.")
            attachment = {k: v for k, v in data.items()
                          if k in ASSEMBLY_ATTACHMENT_FIELDS}
            if attachment.get('ballot_id'):
                ballot = self.get_ballot(rs, attachment['ballot_id'])
                if ballot['vote_begin'] < now():
                    raise ValueError(locked_msg)
                assembly_id = ballot['assembly_id']
            else:
                assembly_id = attachment['assembly_id']
            assembly = self.get_assembly(rs, assembly_id)
            if not assembly['is_active']:
                raise ValueError(locked_msg)
            new_id = self.sql_insert(rs, "assembly.attachments", attachment)
            version = {k: v for k, v in data.items()
                            if k in ASSEMBLY_ATTACHMENT_VERSION_FIELDS}
            version['version'] = 1
            version['attachment_id'] = new_id
            version['file_hash'] = get_hash(content)
            code = self.sql_insert(rs, "assembly.attachment_versions", version)
            if not code:
                raise RuntimeError(n_("Something went wrong."))
            path = self.attachment_base_path / f"{new_id}_v1"
            if path.exists():
                raise RuntimeError(n_("File already exists."))
            with open(path, "wb") as f:
                f.write(content)
            assembly_id = data.get('assembly_id') or self.get_assembly_id(
                rs, ballot_id=data['ballot_id'])
            self.assembly_log(rs, const.AssemblyLogCodes.attachment_added,
                              assembly_id=assembly_id,
                              change_note=version['title'])
            return new_id

    @access("assembly")
    def change_attachment_link(self, rs: RequestState,
                               data: CdEDBObject) -> DefaultReturnCode:
        """Change the association of an attachment.

        It is not allowed to modify an attachment of a ballot that
        has started voting or of an assembly that has been concluded.

        It is not allowed to change the associated ballot to a ballot that has
        started voting.

        It is not allowed to change the (indirectly) associated assembly of
        an attachment.
        """
        data = affirm("assembly_attachment", data)
        with Atomizer(rs):
            # Do some checks to make sure we are not illegaly modifying ballots.
            locked_msg = n_("Unable to change attachment once voting has begun"
                            " or the assembly has been concluded.")
            attachment = self.get_attachment(rs, data['id'])
            old_assembly_id = self.get_assembly_id(rs, attachment_id=data['id'])
            new_assembly_id = data.get('assembly_id') or self.get_assembly_id(
                rs, ballot_id=data['ballot_id'])
            if old_assembly_id != new_assembly_id:
                raise ValueError(n_("Cannot change to a different assembly."))
            assembly = self.get_assembly(rs, old_assembly_id)
            if not self.is_presider(rs, assembly_id=assembly['id']):
                raise PrivilegeError(n_("Must have privileged access to change"
                                        " attachment link."))
            if not assembly['is_active']:
                raise ValueError(locked_msg)
            old_ballot_id = attachment['ballot_id']
            new_ballot_id = data['ballot_id']
            ballot_ids = set(x for x in (old_ballot_id, new_ballot_id) if x)
            ballots = self.get_ballots(rs, ballot_ids).values()
            for ballot in ballots:
                if ballot['vote_begin'] < now():
                    raise ValueError(locked_msg)

            # Actually perform the change.
            ret = self.sql_update(rs, "assembly.attachments", data)
            self.assembly_log(rs, const.AssemblyLogCodes.attachment_changed,
                              assembly_id=old_assembly_id,
                              change_note=data['id'])
            return ret

    @access("assembly")
    def delete_attachment_blockers(self, rs: RequestState,
                                   attachment_id: int) -> DeletionBlockers:
        """Determine what keeps an attachment from being deleted.

        Possible blockers:

        * versions: All version entries for the attachment including versions,
            that were deleted.
        * vote_begin: The associated ballot has begun voting. Prevents deletion.
        * is_active: The associated assembly has concluded. Prevents deletion.

        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        attachment_id = affirm("id", attachment_id)
        blockers = {}

        if not self.is_presider(rs, attachment_id=attachment_id):
            raise PrivilegeError(n_(
                "Must have privileged access to delete attachment."))

        versions = self.get_attachment_history(rs, attachment_id)
        if versions:
            blockers["versions"] = [v for v in versions]

        attachment = self.get_attachment(rs, attachment_id)
        if attachment['ballot_id']:
            ballot = self.get_ballot(rs, attachment['ballot_id'])
            if ballot['vote_begin'] < now():
                blockers["vote_begin"] = ballot["vote_begin"]
            assembly = self.get_assembly(rs, ballot["assembly_id"])
        else:
            assembly = self.get_assembly(rs, attachment["assembly_id"])
        if not assembly["is_active"]:
            blockers["is_active"] = assembly["id"]

        return blockers

    @access("assembly")
    def delete_attachment(self, rs: RequestState, attachment_id: int,
                          cascade: Collection[str] = None) -> DefaultReturnCode:
        """Remove an attachment."""
        attachment_id = affirm("id", attachment_id)
        blockers = self.delete_attachment_blockers(rs, attachment_id)
        if blockers.keys() & {"vote_begin", "is_active"}:
            raise ValueError(n_("Unable to delete attachment once voting has "
                                "begun or the assembly has been concluded."))
        cascade = affirm_set("str", cascade or set()) & blockers.keys()

        if blockers.keys() - cascade:
            raise ValueError(n_("Deletion of %(type)s blocked by %(block)s."),
                             {
                                 "type": "assembly attachment",
                                 "block": blockers.keys() - cascade,
                             })

        ret = 1
        with Atomizer(rs):
            assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
            if not self.is_presider(rs, assembly_id=assembly_id):
                raise PrivilegeError(n_("Must have privileged access to delete"
                                        " attachment."))
            if cascade:
                if "versions" in cascade:
                    ret *= self.sql_delete(rs, "assembly.attachment_versions",
                                           (attachment_id,), "attachment_id")
                    for version in blockers["versions"]:
                        filename = f"{attachment_id}_v{version}"
                        path = self.attachment_base_path / filename
                        if path.exists():
                            path.unlink()
                blockers = self.delete_attachment_blockers(rs, attachment_id)

            if not blockers:
                ret *= self.sql_delete_one(
                    rs, "assembly.attachments", attachment_id)
                self.assembly_log(rs, const.AssemblyLogCodes.attachment_removed,
                                  assembly_id,
                                  change_note=str(attachment_id))
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})
        return ret

    @access("assembly")
    def get_current_versions(self, rs: RequestState,
                             attachment_ids: Collection[int],
                             include_deleted: bool = False) -> Dict[int, int]:
        """Get the most recent version numbers for the given attachments."""
        attachment_ids = affirm_set("id", attachment_ids)
        with Atomizer(rs):
            if not self.check_attachment_access(rs, attachment_ids):
                raise PrivilegeError(n_("Not privileged."))
            query = ("SELECT attachment_id, MAX(version) as version"
                     " FROM assembly.attachment_versions"
                     " WHERE {} GROUP BY attachment_id")
            constraints = ["attachment_id = ANY(%s)"]
            params = [attachment_ids]
            data = self.query_all(
                rs, query.format(" AND ".join(constraints)), params)
            ret = {e["attachment_id"]: e["version"] for e in data}
            if not include_deleted:
                constraints.append("dtime IS NULL")
                data = self.query_all(
                    rs, query.format(" AND ".join(constraints)), params)
                ret.update({e["attachment_id"]: e["version"] for e in data})
            return ret

    class GetCurrentVersion(Protocol):
        def __call__(self, rs: RequestState, attachment_id: int,
                     include_deleted: bool = False) -> int: ...
    get_current_version: GetCurrentVersion
    get_current_version = singularize(
        get_current_versions, "attachment_ids", "attachment_id")

    @access("assembly")
    def add_attachment_version(self, rs: RequestState, data: CdEDBObject,
                               content: bytes) -> DefaultReturnCode:
        """Add a new version of an attachment.

        This is not allowed if the associated ballot has begun voting or if
        the (indirectly) associated assembly has concluded.
        """
        data = affirm("assembly_attachment_version", data, creation=True)
        content = affirm("bytes", content)
        attachment_id = data['attachment_id']
        with Atomizer(rs):
            if self.check_attachment_locked(rs, attachment_id):
                raise ValueError(n_(
                    "Unable to change attachment once voting has begun or the "
                    "assembly has been concluded."))
            version = self.get_current_version(
                rs, attachment_id, include_deleted=True) + 1
            data['version'] = version
            data['file_hash'] = get_hash(content)
            ret = self.sql_insert(rs, "assembly.attachment_versions", data)
            path = self.attachment_base_path / f"{attachment_id}_v{version}"
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
                assembly_id, change_note=f"{data['title']}: Version {version}")
        return ret

    @access("assembly")
    def change_attachment_version(self, rs: RequestState,
                                  data: CdEDBObject) -> DefaultReturnCode:
        """Alter a version of an attachment.

        This is not allowed if the associated ballot has begun voting or if
        the (indirectly) associated assembly has concluded.
        """
        data = affirm("assembly_attachment_version", data)
        attachment_id = data.pop('attachment_id')
        version = data.pop('version')
        with Atomizer(rs):
            if not self.is_presider(rs, attachment_id=attachment_id):
                raise PrivilegeError(n_("Must have privileged access to change"
                                        " attachment version."))
            if self.check_attachment_locked(rs, attachment_id):
                raise ValueError(n_(
                    "Unable to change attachment once voting has begun or the "
                    "assembly has been concluded."))
            keys = tuple(data.keys())
            setters = ", ".join(f"{k} = %s" for k in keys)
            query = (f"UPDATE assembly.attachment_versions SET {setters}"
                     f" WHERE attachment_id = %s AND version = %s")
            params = tuple(data[k] for k in keys) + (attachment_id, version)
            ret = self.query_exec(rs, query, params)
            assembly_id = self.get_assembly_id(rs, attachment_id=attachment_id)
            self.assembly_log(
                rs, const.AssemblyLogCodes.attachment_version_changed,
                assembly_id, change_note=f"{data['title']}: Version {version}")
            return ret

    @access("assembly")
    def remove_attachment_version(self, rs: RequestState, attachment_id: int,
                                  version: int) -> DefaultReturnCode:
        """Remove a version of an attachment. Leaves other versions intact.

        This is not allowed if the associated ballot has begun voting or if
        the (indirectly) associated assembly has concluded.
        """
        attachment_id = affirm("id", attachment_id)
        version = affirm("id", version)
        with Atomizer(rs):
            if not self.is_presider(rs, attachment_id=attachment_id):
                raise PrivilegeError(n_("Must have privileged access to remove"
                                        " attachment version."))
            if self.check_attachment_locked(rs, attachment_id):
                raise ValueError(n_(
                    "Unable to change attachment once voting has begun or the "
                    "assembly has been concluded."))
            history = self.get_attachment_history(rs, attachment_id)
            if version not in history:
                raise ValueError(n_("This version does not exist."))
            if history[version]['dtime']:
                raise ValueError(n_("This version has already been deleted."))
            attachment = self.get_attachment(rs, attachment_id)
            if attachment['num_versions'] <= 1:
                raise ValueError(n_("Cannot remove the last remaining version "
                                    "of an attachment."))
            deletor = {
                'attachment_id': attachment_id,
                'version': version,
                'dtime': now(),
                'title': None,
                'authors': None,
                'filename': None,
            }

            keys = tuple(deletor.keys())
            setters = ", ".join(f"{k} = %s" for k in keys)
            query = (f"UPDATE assembly.attachment_versions SET {setters}"
                     f" WHERE attachment_id = %s AND version = %s")
            params = tuple(deletor[k] for k in keys) + (attachment_id, version)
            ret = self.query_exec(rs, query, params)

            if ret:
                path = self.attachment_base_path / f"{attachment_id}_v{version}"
                if path.exists():
                    path.unlink()
                assembly_id = self.get_assembly_id(
                    rs, attachment_id=attachment_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.attachment_version_removed,
                    assembly_id, change_note=f"{history[version]['title']}:"
                                             f" Version {version}")
            return ret

    @access("assembly")
    def get_attachment_content(self, rs: RequestState, attachment_id: int,
                               version: int = None) -> Union[bytes, None]:
        """Get the content of an attachment. Defaults to most recent version."""
        attachment_id = affirm("id", attachment_id)
        if not self.check_attachment_access(rs, (attachment_id,)):
            raise PrivilegeError(n_("Not privileged."))
        version = affirm("id_or_None", version) or self.get_current_version(
            rs, attachment_id, include_deleted=False)
        path = self.attachment_base_path / f"{attachment_id}_v{version}"
        if path.exists():
            with open(path, "rb") as f:
                return f.read()
        return None

    @access("assembly")
    def list_attachments(self, rs: RequestState, *, assembly_id: int = None,
                         ballot_id: int = None) -> Set[int]:
        """List all files attached to an assembly/ballot.

        Files can either be attached to an assembly or ballot, but not
        to both at the same time.

        Exactly one of the inputs has to be provided.
        """
        if assembly_id is None and ballot_id is None:
            raise ValueError(n_("No input specified."))
        if assembly_id is not None and ballot_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
        if not self.may_access(rs, assembly_id=assembly_id,
                                 ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        key = None
        if assembly_id is not None:
            column = "assembly_id"
            key = assembly_id
        else:
            column = "ballot_id"
            key = ballot_id

        data = self.sql_select(rs, "assembly.attachments", ("id",),
                               (key,), entity_key=column)
        return {e['id'] for e in data}

    def _get_attachment_infos(self, rs: RequestState,
                              attachment_ids: Collection[int]
                              ) -> CdEDBObjectMap:
        """Internal helper to retrieve attachment data without access check."""
        attachment_ids = affirm_set("id", attachment_ids)
        query = f"""SELECT
                {', '.join(ASSEMBLY_ATTACHMENT_FIELDS +
                           ('num_versions', 'current_version'))}
            FROM (
                (
                    SELECT
                        {', '.join(ASSEMBLY_ATTACHMENT_FIELDS)}
                    FROM
                        assembly.attachments
                    WHERE
                        id = ANY(%s)
                ) AS attachments
                LEFT OUTER JOIN (
                    SELECT
                        attachment_id, COUNT(version) as num_versions,
                        MAX(version) as current_version
                    FROM
                        assembly.attachment_versions
                    WHERE
                        dtime IS NULL
                    GROUP BY
                        attachment_id
                ) AS count ON attachments.id = count.attachment_id
            )"""
        params = (attachment_ids,)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e for e in data}
        return ret
    _get_attachment_info: Callable[[RequestState, int], CdEDBObject]
    _get_attachment_info = singularize(
        _get_attachment_infos, "attachment_ids", "attachment_id")

    @access("assembly")
    def get_attachments(self, rs: RequestState,
                        attachment_ids: Collection[int]) -> CdEDBObjectMap:
        """Retrieve data on attachments"""
        attachment_ids = affirm_set("id", attachment_ids)
        with Atomizer(rs):
            if not self.check_attachment_access(rs, attachment_ids):
                raise PrivilegeError(n_("Not privileged."))
            return self._get_attachment_infos(rs, attachment_ids)
    get_attachment: Callable[['AssemblyBackend', RequestState, int],
                             CdEDBObject]
    get_attachment = singularize(
        get_attachments, "attachment_ids", "attachment_id")
