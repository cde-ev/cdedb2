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
import string

from cdedb.backend.common import (
    access, affirm_validation as affirm, affirm_set_validation as affirm_set,
    Silencer, singularize, AbstractBackend, internal_access)
from cdedb.common import (
    n_, glue, unwrap, ASSEMBLY_FIELDS, BALLOT_FIELDS, FUTURE_TIMESTAMP, now,
    ASSEMBLY_ATTACHMENT_FIELDS, schulze_evaluate, EntitySorter,
    extract_roles, PrivilegeError, ASSEMBLY_BAR_MONIKER, json_serialize,
    implying_realms, xsorted)
from cdedb.security import secure_random_ascii
from cdedb.query import QueryOperators
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const


class AssemblyBackend(AbstractBackend):
    """This is an entirely unremarkable backend."""
    realm = "assembly"

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def may_assemble(self, rs, *, assembly_id=None, ballot_id=None,
                     persona_id=None):
        """Helper to check authorization.

        The deal is that members may access anything and assembly users
        may access any assembly in which they are participating. This
        especially allows people who have "cde", but not "member" in
        their roles, to access only those assemblies they participated
        in.

        Exactly one of the two id parameters has to be provided

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type ballot_id: int
        :type persona_id: int or None
        :param persona_id: If not provided the current user is used.
        :rtype: bool
        """
        if "member" in rs.user.roles:
            return True
        return self.check_attendance(
            rs, assembly_id=assembly_id, ballot_id=ballot_id,
            persona_id=persona_id)

    @access("persona")
    def may_view(self, rs, assembly_id, persona_id=None):
        """Variant of `may_assemble` with input validation. To be used by
         frontends to find out if assembly is visible.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type persona_id: int or None
        :param persona_id: If not provided the current user is used.
        :rtype: bool
        """
        assembly_id = affirm("id", assembly_id)
        persona_id = affirm("id_or_None", persona_id)
        return self.may_assemble(rs, assembly_id=assembly_id,
                                 persona_id=persona_id)

    @staticmethod
    def encrypt_vote(salt, secret, vote):
        """Compute a cryptographically secure hash from a vote.

        This hash is used to ensure that only knowledge of the secret
        allows modification of the vote. We use SHA512 as hash.

        :type salt: str
        :type secret: str
        :type vote: str
        :rtype: str
        """
        h = hmac.new(salt.encode('ascii'), digestmod="sha512")
        h.update(secret.encode('ascii'))
        h.update(vote.encode('ascii'))
        return h.hexdigest()

    def retrieve_vote(self, rs, ballot_id, secret):
        """Low level function for looking up a vote.

        This is a brute force algorithm checking each vote, whether it
        belongs to the passed secret. This is impossible to do more
        efficiently by design. Otherwise some quality of our voting
        process would be compromised.

        This assumes, that a vote actually exists and throws an error if
        not.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :type secret: str
        :rtype: str
        """
        all_votes = self.sql_select(
            rs, "assembly.votes", ("id", "vote", "salt", "hash"),
            (ballot_id,), entity_key="ballot_id")
        for v in all_votes:
            if v['hash'] == self.encrypt_vote(v['salt'], secret, v['vote']):
                return v
        raise ValueError(n_("No vote found."))

    def assembly_log(self, rs, code, assembly_id, persona_id=None,
                     additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type code: int
        :param code: One of
          :py:class:`cdedb.database.constants.AssemblyLogCodes`.
        :type assembly_id: int or None
        :type persona_id: int or None
        :param persona_id: ID of affected user (like who was subscribed).
        :type additional_info: str or None
        :param additional_info: Infos not conveyed by other columns.
        :rtype: int
        :returns: default return code
        """
        if rs.is_quiet:
            return 0
        # do not use sql_insert since it throws an error for selecting the id
        query = glue(
            "INSERT INTO assembly.log",
            "(code, assembly_id, submitted_by, persona_id, additional_info)",
            "VALUES (%s, %s, %s, %s, %s)")
        return self.query_exec(
            rs, query, (code, assembly_id, rs.user.persona_id, persona_id,
                        additional_info))

    @access("assembly_admin")
    def retrieve_log(self, rs, codes=None, assembly_id=None, start=None,
                     stop=None, persona_id=None, submitted_by=None,
                     additional_info=None, time_start=None, time_stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type codes: [int] or None
        :type assembly_id: int or None
        :type start: int or None
        :type stop: int or None
        :type persona_id: int or None
        :type submitted_by: int or None
        :type additional_info: str or None
        :type time_start: datetime or None
        :type time_stop: datetime or None
        :rtype: [{str: object}]
        """
        assembly_id = affirm("id_or_None", assembly_id)
        return self.generic_retrieve_log(
            rs, "enum_assemblylogcodes", "assembly", "assembly.log", codes,
            entity_id=assembly_id, start=start, stop=stop,
            persona_id=persona_id, submitted_by=submitted_by,
            additional_info=additional_info, time_start=time_start,
            time_stop=time_stop)

    @access("assembly_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.common.RequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
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

    @internal_access("persona")
    def check_attendance(self, rs, *, assembly_id=None, ballot_id=None,
                         persona_id=None):
        """Check wether a persona attends a specific assembly/ballot.

        Exactly one of the inputs assembly_id and ballot_id has to be
        provided.

        This does not check for authorization since it is used during
        the authorization check.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int or None
        :type ballot_id: int or None
        :type persona_id: int or None
        :param persona_id: If not provided the current user is used.
        :rtype: bool
        """
        if assembly_id is None and ballot_id is None:
            raise ValueError(n_("No input specified."))
        if assembly_id is not None and ballot_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        if persona_id is None:
            persona_id = rs.user.persona_id
        with Atomizer(rs):
            if ballot_id is not None:
                assembly_id = unwrap(self.sql_select_one(
                    rs, "assembly.ballots", ("assembly_id",), ballot_id))
            query = glue("SELECT id FROM assembly.attendees",
                         "WHERE assembly_id = %s and persona_id = %s")
            return bool(self.query_one(
                rs, query, (assembly_id, persona_id)))

    @access("assembly")
    def does_attend(self, rs, *, assembly_id=None, ballot_id=None):
        """Check wether this persona attends a specific assembly/ballot.

        Exactly one of the inputs has to be provided.

        This does not check for authorization since it is used during
        the authorization check.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int or None
        :type ballot_id: int or None
        :rtype: bool
        """
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
        return self.check_attendance(rs, assembly_id=assembly_id,
                                     ballot_id=ballot_id)

    @access("assembly")
    def check_attends(self, rs, persona_id, assembly_id):
        """Check whether a user attends an assembly.

        This is mostly used for checking mailinglist eligibility.

        As assembly attendees are public to all assembly users, this does not
        check for any privileges,

        :type rs: :py:class:`cdedb.common.RequestState`
        :type persona_id: int
        :type assembly_id: int
        :rtype: bool
        """
        persona_id = affirm("id", persona_id)
        assembly_id = affirm("id", assembly_id)

        return self.check_attendance(
            rs, assembly_id=assembly_id, persona_id=persona_id)

    @access("assembly")
    def list_attendees(self, rs, assembly_id):
        """Everybody who has subscribed for a specific assembly.

        This is an unprivileged operation in that everybody (with access
        to the assembly realm) may view this list -- no condition of
        being an attendee. This seems reasonable since assemblies should
        be public to the entire association.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :rtype: [int]
        """
        assembly_id = affirm("id", assembly_id)
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise PrivilegeError(n_("Not privileged."))
        attendees = self.sql_select(
            rs, "assembly.attendees", ("persona_id",), (assembly_id,),
            entity_key="assembly_id")
        return {e['persona_id'] for e in attendees}

    @access("persona")
    def list_assemblies(self, rs, is_active=None):
        """List all assemblies.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type is_active: bool or None
        :param is_active: If not None list only assemblies which have this
          activity status.
        :rtype: {int: {str: str}}
        :returns: Mapping of event ids to dict with title, activity status and
          signup end. The latter is used to sort the assemblies in index.
        """
        is_active = affirm("bool_or_None", is_active)
        query = ("SELECT id, title, signup_end, is_active "
                 "FROM assembly.assemblies")
        params = tuple()
        if is_active is not None:
            query = glue(query, "WHERE is_active = %s")
            params = (is_active,)
        data = self.query_all(rs, query, params)
        ret = {e['id']: e for e in data}
        if "assembly" not in rs.user.roles:
            ret = {}
        elif "member" not in rs.user.roles:
            ret = {k: v for k, v in ret.items()
                   if self.check_attendance(rs, assembly_id=k)}
        return ret

    @access("assembly")
    @singularize("get_assembly")
    def get_assemblies(self, rs, ids):
        """Retrieve data for some assemblies.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        if not all(self.may_assemble(rs, assembly_id=anid) for anid in ids):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "assembly.assemblies", ASSEMBLY_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("assembly_admin")
    def set_assembly(self, rs, data):
        """Update some keys of an assembly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("assembly", data)
        assembly = unwrap(self.get_assemblies(rs, (data['id'],)))
        if not assembly['is_active']:
            raise ValueError(n_("Assembly already concluded."))
        ret = self.sql_update(rs, "assembly.assemblies", data)
        self.assembly_log(rs, const.AssemblyLogCodes.assembly_changed,
                          data['id'])
        return ret

    @access("assembly_admin")
    def create_assembly(self, rs, data):
        """Make a new assembly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new assembly
        """
        data = affirm("assembly", data, creation=True)
        new_id = self.sql_insert(rs, "assembly.assemblies", data)
        self.assembly_log(rs, const.AssemblyLogCodes.assembly_created, new_id)
        return new_id

    @access("assembly_admin")
    def delete_assembly_blockers(self, rs, assembly_id):
        """Determine whether an assembly is deletable.

        Possible blockers:

        * ballots: These can have their own blockers like vote_begin.
        * vote_begin: Ballots where voting has begun. Prevents deletion.
        * attendees: Rows of the assembly.attendees table.
        * attachments: All attachments associated with the assembly and it's
                       ballots
        * log: All log entries associated with this assembly.
        * mailinglists: Mailinglists referencing this assembly. The
                        references will be removed, but the lists won't be
                        deleted.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :rtype: {str: [int]}
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
    def delete_assembly(self, rs, assembly_id, cascade=None):
        """Remove an assembly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
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
                        for attachment_id in blockers["attachments"]:
                            ret *= self.remove_attachment(rs, attachment_id)
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
                    assembly_id=None, additional_info=assembly["title"])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "assembly", "block": blockers.keys()})

        return ret

    @access("assembly")
    def list_ballots(self, rs, assembly_id):
        """List all ballots of an assembly.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :rtype: {int: str}
        :returns: Mapping of ballot ids to titles.
        """
        assembly_id = affirm("id", assembly_id)
        if not self.may_assemble(rs, assembly_id=assembly_id):
            raise PrivilegeError(n_("Not privileged."))
        data = self.sql_select(rs, "assembly.ballots", ("id", "title"),
                               (assembly_id,), entity_key="assembly_id")
        return {e['id']: e['title'] for e in data}

    @access("assembly")
    @singularize("get_ballot")
    def get_ballots(self, rs, ids):
        """Retrieve data for some ballots,

        They do not need to be associated to the same assembly. This has an
        additional field 'candidates' listing the available candidates for
        this ballot.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)

        with Atomizer(rs):
            data = self.sql_select(rs, "assembly.ballots", BALLOT_FIELDS, ids)
            ret = {e['id']: e for e in data}
            data = self.sql_select(
                rs, "assembly.candidates",
                ("id", "ballot_id", "description", "moniker"), ids,
                entity_key="ballot_id")
            for anid in ids:
                candidates = {e['id']: e for e in data
                              if e['ballot_id'] == anid}
                assert ('candidates' not in ret[anid])
                ret[anid]['candidates'] = candidates
            if "member" not in rs.user.roles:
                ret = {k: v for k, v in ret.items()
                       if self.check_attendance(rs, ballot_id=k)}
        return ret

    @access("assembly_admin")
    def set_ballot(self, rs, data):
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("ballot", data)

        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_ballots(rs, (data['id'],)))
            if now() > current['vote_begin']:
                raise ValueError(n_("Unable to modify active ballot."))
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            if len(bdata) > 1:
                ret *= self.sql_update(rs, "assembly.ballots", bdata)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_changed,
                    current['assembly_id'], additional_info=current['title'])
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
                for x in new:
                    new_candidate = copy.deepcopy(data['candidates'][x])
                    new_candidate['ballot_id'] = data['id']
                    ret *= self.sql_insert(rs, "assembly.candidates",
                                           new_candidate)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_added,
                        current['assembly_id'],
                        additional_info=data['candidates'][x]['moniker'])
                # updated
                for x in updated:
                    update = copy.deepcopy(data['candidates'][x])
                    update['id'] = x
                    ret *= self.sql_update(rs, "assembly.candidates", update)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_updated,
                        current['assembly_id'],
                        additional_info=current['candidates'][x]['moniker'])
                # deleted
                if deleted:
                    ret *= self.sql_delete(rs, "assembly.candidates", deleted)
                    for x in deleted:
                        self.assembly_log(
                            rs, const.AssemblyLogCodes.candidate_removed,
                            current['assembly_id'],
                            additional_info=current['candidates'][x]['moniker'])
        return ret

    @access("assembly_admin")
    def create_ballot(self, rs, data):
        """Make a new ballot

        This has to take care to keep the voter register consistent.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("ballot", data, creation=True)

        with Atomizer(rs):
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
                          data['assembly_id'], additional_info=data['title'])
        return new_id

    @access("assembly_admin")
    def delete_ballot_blockers(self, rs, ballot_id):
        """Determine whether a ballot is deletable.

        Possible blockers:

        * vote_begin: Whether voting on the ballot has begun.
                      Prevents deletion.
        * candidates: Rows in the assembly.candidates table.
        * attachments: All attachments associated with this ballot.
        * voters: Rows in the assembly.voters table. These do not actually
                  mean that anyone has voted for that ballot, as they are
                  created upon assembly signup and/or ballot creation.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :rtype: {str: [int]}
        :return: List of blockers, separated by type. The values of the dict
            are the ids of the blockers.
        """
        ballot_id = affirm("id", ballot_id)
        blockers = {}

        ballot = self.get_ballot(rs, ballot_id)
        if now() > ballot['vote_begin']:
            # Unable to remove active ballot
            blockers["vote_begin"] = ballot_id
        if ballot['candidates']:
            # Ballot still has candidates
            blockers["candidates"] = [anid for anid in ballot["candidates"]]

        attachments = self.list_attachments(rs, ballot_id=ballot_id)
        if attachments:
            # Ballot still has attachments
            blockers["attachments"] = [anid for anid in attachments]

        voters = self.sql_select(rs, "assembly.voter_register", ("id", ),
                                 (ballot_id,), entity_key="ballot_id")
        if voters:
            # Ballot still has voters
            blockers["voters"] = [e["id"] for e in voters]

        return blockers

    @access("assembly_admin")
    def delete_ballot(self, rs, ballot_id, cascade=None):
        """Remove a ballot.

        .. note:: As with modification of ballots this is forbidden
          after voting has started.

        .. note:: As with :py:func:`remove_attachment` the frontend has to take
          care of the actual file manipulation for attachments.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :type cascade: {str} or None
        :param cascade: Specify which deletion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
        :returns: default return code
        """
        ballot_id = affirm("id", ballot_id)
        blockers = self.delete_ballot_blockers(rs, ballot_id)
        if "vote_begin" in blockers:
            raise ValueError(n_("Unable to remove active ballot."))
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
            # cascade specified blockers
            if cascade:
                if "vote_begin" in cascade:
                    raise ValueError(n_("Unable to cascade %(blocker)s."),
                                     {"blocker": "vote_begin"})
                if "candidates" in cascade:
                    ret *= self.sql_delete(
                        rs, "assembly.candidates", blockers["candidates"])
                if "attachments" in cascade:
                    with Silencer(rs):
                        for attachment_id in blockers["attachments"]:
                            ret *= self.remove_attachment(rs, attachment_id)
                if "voters" in cascade:
                    ret *= self.sql_delete(
                        rs, "assembly.voter_register", blockers["voters"])

                # check if ballot is deletable after maybe cascading
                blockers = self.delete_ballot_blockers(rs, ballot_id)

            if not blockers:
                ret *= self.sql_delete_one(rs, "assembly.ballots", ballot_id)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_deleted,
                    current['assembly_id'], additional_info=current['title'])
            else:
                raise ValueError(
                    n_("Deletion of %(type)s blocked by %(block)s."),
                    {"type": "ballot", "block": blockers.keys()})
        return ret

    @access("assembly")
    def check_voting_priod_extension(self, rs, ballot_id):
        """Update extension status w.r.t. quorum.

        After the normal voting period has ended an extension is enacted
        if the quorum is not met. The quorum may be zero in which case
        it is automatically met.

        This is an unprivileged operation so it can be done
        automatically by everybody when viewing a ballot. It is not
        allowed to call this before the normal voting period has
        expired.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :rtype: bool
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
            }
            # do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            if update['extended']:
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_extended,
                    ballot['assembly_id'], additional_info=ballot['title'])
        return update['extended']

    def process_signup(self, rs, assembly_id, persona_id):
        """Helper to perform the actual signup

        This has to take care to keep the voter register consistent.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type persona_id: int
        :rtype: str or None
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

            new_attendee = {
                'assembly_id': assembly_id,
                'persona_id': persona_id,
                'secret': secure_random_ascii(),
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
            return new_attendee['secret']

    @access("assembly_admin")
    def external_signup(self, rs, assembly_id, persona_id):
        """Make a non-member attend an assembly.

        Those are not allowed to subscribe themselves, but must be added
        by an admin. On the other hand we disallow this action for members.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type persona_id: int
        :rtype: str or None
        :returns: The secret if a new secret was generated or None if we
          already attend.
        """
        assembly_id = affirm("id", assembly_id)
        persona_id = affirm("id", persona_id)

        roles = extract_roles(self.core.get_persona(rs, persona_id))
        if "member" in roles:
            raise ValueError(n_("Not allowed for members."))
        if "assembly" not in roles:
            raise ValueError(n_("Only allowed for assembly users."))

        return self.process_signup(rs, assembly_id, persona_id)

    @access("member")
    def signup(self, rs, assembly_id):
        """Attend the assembly.

        This does not accept a persona_id on purpose.

        This has to take care to keep the voter register consistent.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :rtype: str or None
        :returns: The secret if a new secret was generated or None if we
          already attend.
        """
        assembly_id = affirm("id", assembly_id)

        return self.process_signup(rs, assembly_id, rs.user.persona_id)

    @access("assembly")
    def vote(self, rs, ballot_id, vote, secret):
        """Submit a vote.

        This does not accept a persona_id on purpose.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :type vote: str
        :type secret: str or None
        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :rtype: int
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
            if not has_voted:
                salt = secure_random_ascii()
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
    def has_voted(self, rs, ballot_id):
        """Look up whether the user has voted in a ballot.

        It is only allowed to call this if we attend the ballot.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :rtype: bool
        """
        ballot_id = affirm("id", ballot_id)

        if not self.check_attendance(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Must attend the ballot."))

        query = glue("SELECT has_voted FROM assembly.voter_register",
                     "WHERE ballot_id = %s and persona_id = %s")
        has_voted = unwrap(
            self.query_one(rs, query, (ballot_id, rs.user.persona_id)))
        return has_voted

    @access("assembly")
    def count_votes(self, rs, ballot_id):
        """Look up how many attendees had already voted in a ballot.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :rtype: int
        """
        ballot_id = affirm("id", ballot_id)

        query = glue("SELECT COUNT(*) AS count FROM assembly.voter_register",
                     "WHERE ballot_id = %s and has_voted = True")
        count_votes = unwrap(self.query_one(rs, query, (ballot_id,)))
        return count_votes

    @access("assembly")
    def get_vote(self, rs, ballot_id, secret):
        """Look up a vote.

        This does not accept a persona_id on purpose.

        It is only allowed to call this if we attend the ballot.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :type secret: str or None
        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :rtype: str or None
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
    def tally_ballot(self, rs, ballot_id):
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

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ballot_id: int
        :rtype: bool
        :returns: True if a new result file was generated and False if the
          ballot was already tallied.
        """
        ballot_id = affirm("id", ballot_id)

        # We do not use jinja here as it is currently only used in the
        # frontend.
        template = string.Template("""{
    "assembly": ${ASSEMBLY},
    "ballot": ${BALLOT},
    "result": ${RESULT},
    "candidates": {
        ${CANDIDATES}
    },
    "use_bar": ${USE_BAR},
    "voters": [
        ${VOTERS}
    ],
    "votes": [
        ${VOTES}
    ]
}
""")
        if not self.may_assemble(rs, ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            if ballot['is_tallied']:
                return False
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
            monikers = tuple(
                x['moniker'] for x in ballot['candidates'].values())
            if ballot['use_bar'] or ballot['votes']:
                monikers += (ASSEMBLY_BAR_MONIKER,)
            condensed, detailed = schulze_evaluate([e['vote'] for e in votes],
                                                   monikers)
            update = {
                'id': ballot_id,
                'is_tallied': True,
            }
            # do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            self.assembly_log(
                rs, const.AssemblyLogCodes.ballot_tallied,
                ballot['assembly_id'], additional_info=ballot['title'])

            # now generate the result file
            esc = json_serialize
            assembly = unwrap(
                self.get_assemblies(rs, (ballot['assembly_id'],)))
            candidates = ",\n        ".join(
                "{}: {}".format(esc(c['moniker']), esc(c['description']))
                for c in xsorted(ballot['candidates'].values(),
                                key=lambda x: x['moniker']))
            query = glue("SELECT persona_id FROM assembly.voter_register",
                         "WHERE ballot_id = %s and has_voted = True")
            voter_ids = self.query_all(rs, query, (ballot_id,))
            voters = self.core.get_personas(
                rs, tuple(unwrap(e) for e in voter_ids))
            voters = ("{} {}".format(e['given_names'], e['family_name'])
                      for e in xsorted(voters.values(),
                                      key=EntitySorter.persona))
            voter_list = ",\n        ".join(esc(v) for v in voters)
            votes = xsorted('{{"vote": {}, "salt": {}, "hash": {}}}'.format(
                esc(v['vote']), esc(v['salt']), esc(v['hash'])) for v in votes)
            vote_list = ",\n        ".join(v for v in votes)
            result_file = template.substitute({
                'ASSEMBLY': esc(assembly['title']),
                'BALLOT': esc(ballot['title']),
                'RESULT': esc(condensed),
                'CANDIDATES': candidates,
                'USE_BAR': esc(ballot['use_bar']),
                'VOTERS': voter_list,
                'VOTES': vote_list,
            })
            path = self.conf.STORAGE_DIR / 'ballot_result' / str(ballot_id)
            with open(path, 'w') as f:
                f.write(result_file)
        return True

    @access("assembly_admin")
    def conclude_assembly_blockers(self, rs, assembly_id):
        """Determine whether an assembly may be concluded.

        Possible blockers:

        * is_active: Only active assemblies may be concluded.
        * signup_end: An Assembly may only be concluded when signup is over.
        * ballot: An Assembly may only be concluded when all ballots are
                  tallied.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        """
        assembly_id = affirm("id", assembly_id)
        blockers = {}

        assembly = self.get_assembly(rs, assembly_id)
        if not assembly['is_active']:
            blockers['is_active'] = assembly_id

        timestamp = now()
        if timestamp < assembly['signup_end']:
            blockers["signup_end"] = assembly['signup_end']

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
    def conclude_assembly(self, rs, assembly_id, cascade=None):
        """Do housekeeping after an assembly has ended.

        This mainly purges the secrets which are no longer required for
        updating votes, so that they do not leak in the future.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int
        :type cascade: {str} or None
        :param cascade: Specify which conclusion blockers to cascadingly
            remove or ignore. If None or empty, cascade none.
        :rtype: int
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

    @access("assembly")
    def list_attachments(self, rs, *, assembly_id=None, ballot_id=None):
        """List all files attached to an assembly/ballot.

        Files can either be attached to an assembly or ballot, but not
        to both at the same time.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type assembly_id: int or None
        :type ballot_id: int or None
        :rtype: {int: str}
        :returns: dict mapping attachment ids to titles
        """
        if assembly_id is None and ballot_id is None:
            raise ValueError(n_("No input specified."))
        if assembly_id is not None and ballot_id is not None:
            raise ValueError(n_("Too many inputs specified."))
        assembly_id = affirm("id_or_None", assembly_id)
        ballot_id = affirm("id_or_None", ballot_id)
        if not self.may_assemble(rs, assembly_id=assembly_id,
                                 ballot_id=ballot_id):
            raise PrivilegeError(n_("Not privileged."))

        if assembly_id is not None:
            column = "assembly_id"
            key = assembly_id
        else:
            column = "ballot_id"
            key = ballot_id

        data = self.sql_select(rs, "assembly.attachments", ("id", "title"),
                               (key,), entity_key=column)
        return {e['id']: e['title'] for e in data}

    @access("assembly")
    @singularize("get_attachment")
    def get_attachments(self, rs, ids):
        """Retrieve data on attachments

        :type rs: :py:class:`cdedb.common.RequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_set("id", ids)
        data = self.sql_select(rs, "assembly.attachments",
                               ASSEMBLY_ATTACHMENT_FIELDS, ids)
        ret = {e['id']: e for e in data}
        if "member" not in rs.user.roles:
            ret = {k: v for k, v in ret.items() if self.check_attendance(
                rs, assembly_id=v['assembly_id'], ballot_id=v['ballot_id'])}
        return ret

    @access("assembly_admin")
    def add_attachment(self, rs, data, attachment):
        """Create a new attachment.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type data: {str: object}
        :type attachment: bytes
        :rtype: int
        :returns: id of the new attachment
        """
        data = affirm("assembly_attachment", data)
        if data.get('ballot_id'):
            ballot = unwrap(self.get_ballots(rs, (data['ballot_id'],)))
            if now() > ballot['vote_begin']:
                raise ValueError(n_("Unable to modify active ballot."))
        ret = self.sql_insert(rs, "assembly.attachments", data)
        assembly_id = data.get('assembly_id')
        if not assembly_id:
            ballot = unwrap(self.get_ballots(rs, (data['ballot_id'],)))
            assembly_id = ballot['assembly_id']
        self.assembly_log(rs, const.AssemblyLogCodes.attachment_added,
                          assembly_id, additional_info=data['title'])

        path = (self.conf.STORAGE_DIR / 'assembly_attachment'
                / str(ret))
        with open(str(path), 'wb') as f:
            f.write(attachment)

        return ret

    @access("assembly_admin")
    def remove_attachment(self, rs, attachment_id):
        """Delete an attachment.

        :type rs: :py:class:`cdedb.common.RequestState`
        :type attachment_id: int
        :rtype: int
        :returns: default return code
        """
        attachment_id = affirm("id", attachment_id)
        current = unwrap(self.get_attachments(rs, (attachment_id,)))
        if current['ballot_id']:
            ballot = unwrap(self.get_ballots(rs, (current['ballot_id'],)))
            if now() > ballot['vote_begin']:
                raise ValueError(n_("Unable to modify active ballot."))
        ret = self.sql_delete_one(rs, "assembly.attachments", attachment_id)
        assembly_id = current['assembly_id']
        if not assembly_id:
            ballot = unwrap(self.get_ballots(rs, (current['ballot_id'],)))
            assembly_id = ballot['assembly_id']
        self.assembly_log(rs, const.AssemblyLogCodes.attachment_removed,
                          assembly_id, additional_info=current['title'])

        path = (self.conf.STORAGE_DIR / 'assembly_attachment'
                / str(attachment_id))
        if path.exists():
            path.unlink()

        return ret
