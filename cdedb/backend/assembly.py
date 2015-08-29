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

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize)
from cdedb.common import (
    glue, PrivilegeError, unwrap, ASSEMBLY_FIELDS, BALLOT_FIELDS,
    ASSEMBLY_ATTACHMENT_FIELDS, random_ascii, schulze_evaluate, name_key,
    FUTURE_TIMESTAMP, now)
from cdedb.config import Config
from cdedb.query import QueryOperators
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse
import copy
import datetime
import hashlib
import json
import os.path
import string

class AssemblyBackend(AbstractUserBackend):
    """This is an entirely unremarkable backend."""
    realm = "assembly"
    user_management = {
        "data_table": None,
        "data_fields": None,
        "validator": "persona_data",
        "user_status": const.PersonaStati.assembly_user,
    }

    def establish(self, sessionkey, method, allow_internal=False):
        return super().establish(sessionkey, method,
                                 allow_internal=allow_internal)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

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
        myhash = hashlib.sha512()
        myhash.update(salt.encode('ascii'))
        myhash.update(secret.encode('ascii'))
        myhash.update(vote.encode('ascii'))
        return myhash.hexdigest()

    def retrieve_vote(self, rs, ballot_id, secret):
        """Low level function for looking up a vote.

        This is a brute force algorithm checking each vote, whether it
        belongs to the passed secret. This is impossible to do more
        efficiently by design. Otherwise some quality of our voting
        process would be compromised.

        This assumes, that a vote actually exists and throws an error if
        not.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        raise ValueError("No vote found.")

    @access("assembly_user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("assembly_user")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        return super().get_data(rs, ids)

    @access("assembly_admin")
    def create_user(self, rs, data):
        return super().create_user(rs, data)

    @access("anonymous")
    def genesis_check(self, rs, case_id, secret):
        """Assembly accounts can only be created by admins."""
        raise NotImplementedError("Not available for assembly realm.")

    @access("anonymous")
    def genesis(self, rs, case_id, secret, data):
        """Assembly accounts can only be created by admins."""
        raise NotImplementedError("Not available for assembly realm.")

    def assembly_log(self, rs, code, assembly_id, persona_id=None,
                     additional_info=None):
        """Make an entry in the log.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
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
        ## do not use sql_insert since it throws an error for selecting the id
        query = glue(
            "INSERT INTO assembly.log",
            "(code, assembly_id, submitted_by, persona_id, additional_info)",
            "VALUES (%s, %s, %s, %s, %s)")
        return self.query_exec(
            rs, query, (code, assembly_id, rs.user.persona_id, persona_id,
                        additional_info))

    @access("assembly_admin")
    def retrieve_log(self, rs, codes=None, assembly_id=None,
                     start=None, stop=None):
        """Get recorded activity.

        See
        :py:meth:`cdedb.backend.common.AbstractBackend.generic_retrieve_log`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type codes: [int] or None
        :type assembly_id: int or None
        :type start: int or None
        :type stop: int or None
        :rtype: [{str: object}]
        """
        assembly_id = affirm("int_or_None", assembly_id)
        return self.generic_retrieve_log(
            rs, "enum_assemblylogcodes", "assembly", "assembly.log", codes,
            assembly_id, start, stop)

    @access("assembly_user")
    @singularize("acquire_data_one")
    def acquire_data(self, rs, ids):
        """Return user data sets.

        Since the assembly realm does not define any additional attributes
        this delegates to :py:meth:`cdedb.backend.core.CoreBackend.get_data`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        return self.core.get_data(rs, ids)

    @access("assembly_admin")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str: object}]
        """
        query = affirm("serialized_query", query)
        if query.scope == "qview_generic_user":
            query.constraints.append(("status", QueryOperators.equal,
                                      const.PersonaStati.assembly_user))
            query.spec['status'] = "int"
        else:
            raise RuntimeError("Bad scope.")
        return self.general_query(rs, query)

    @access("assembly_user")
    def does_attend(self, rs, *, assembly_id=None, ballot_id=None):
        """Check wether this persona attends a specific assembly/ballot.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int or None
        :type ballot_id: int or None
        :rtype: bool
        """
        assembly_id = affirm("int_or_None", assembly_id)
        ballot_id = affirm("int_or_None", ballot_id)
        if assembly_id is None and ballot_id is None:
            raise ValueError("No input specified.")
        if assembly_id is not None and ballot_id is not None:
            raise ValueError("Too many inputs specified.")
        with Atomizer(rs):
            if ballot_id is not None:
                assembly_id = unwrap(self.sql_select_one(
                    rs, "assembly.ballots", ("assembly_id",), ballot_id))
            query = glue("SELECT id FROM assembly.attendees",
                         "WHERE assembly_id = %s and persona_id = %s")
            return bool(self.query_one(
                rs, query, (assembly_id, rs.user.persona_id)))

    @access("assembly_user")
    def list_attendees(self, rs, assembly_id):
        """Everybody who has subscribed for a specific assembly.

        This is an unprivileged operation in that everybody (with access
        to the assembly realm) may view this list -- no condition of
        being an attendee. This seems reasonable since assemblies should
        be public to the entire association.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int
        :rtype: [int]
        """
        assembly_id = affirm("int", assembly_id)
        attendees = self.sql_select(
            rs, "assembly.attendees", ("persona_id",), (assembly_id,),
            entity_key="assembly_id")
        return {e['persona_id'] for e in attendees}

    @access("assembly_user")
    def list_assemblies(self, rs, is_active=None):
        """List all assemblies.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type is_active: bool or None
        :param is_active: If not None list only assemblies which have this
          activity status.
        :rtype: {int: {str: str}}
        :returns: Mapping of event ids to dict with title and activity status.
        """
        is_active = affirm("bool_or_None", is_active)
        query = "SELECT id, title, is_active FROM assembly.assemblies"
        params = tuple()
        if is_active is not None:
            query = glue(query, "WHERE is_active = %s")
            params = (is_active,)
        data = self.query_all(rs, query, params)
        return {e['id']: e for e in data}

    @access("assembly_user")
    @singularize("get_assembly_data_one")
    def get_assembly_data(self, rs, ids):
        """Retrieve data for some assemblies.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "assembly.assemblies", ASSEMBLY_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("assembly_admin")
    def set_assembly_data(self, rs, data):
        """Update some keys of an assembly.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("assembly_data", data)
        assembly = unwrap(self.get_assembly_data(rs, (data['id'],)))
        if not assembly['is_active']:
            raise ValueError("Assembly already concluded.")
        ret = self.sql_update(rs, "assembly.assemblies", data)
        self.assembly_log(rs, const.AssemblyLogCodes.assembly_changed,
                          data['id'])
        return ret

    @access("assembly_admin")
    def create_assembly(self, rs, data):
        """Make a new assembly.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new assembly
        """
        data = affirm("assembly_data", data, creation=True)
        new_id = self.sql_insert(rs, "assembly.assemblies", data)
        self.assembly_log(rs, const.AssemblyLogCodes.assembly_created, new_id)
        return new_id

    @access("assembly_user")
    def list_ballots(self, rs, assembly_id):
        """List all ballots of an assembly.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int
        :rtype: {int: str}
        :returns: Mapping of ballot ids to titles.
        """
        assembly_id = affirm("int", assembly_id)
        data = self.sql_select(rs, "assembly.ballots", ("id", "title"),
                               (assembly_id,), entity_key="assembly_id")
        return {e['id']: e['title'] for e in data}

    @access("assembly_user")
    @singularize("get_ballot")
    def get_ballots(self, rs, ids):
        """Retrieve data for some ballots,

        They do not need to be associated to the same assembly. This has an
        additional field 'candidates' listing the available candidates for
        this ballot.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)

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
                assert('candidates' not in ret[anid])
                ret[anid]['candidates'] = candidates
        return ret

    @access("assembly_admin")
    def set_ballot(self, rs, data):
        """Update some keys of ballot.

        If the key 'candidates' is present, the associated dict mapping the
        candidate ids to the respective data sets can contain an arbitrary
        number of entities, absent entities are not modified.

        Any valid candidate id that is present has to map to a (partial or
        complete) data set or ``None``. In the first case the candidate is
        updated, in the second case it is deleted.

        Any invalid candidate id (that is negative integer) has to map to a
        complete data set which will be used to create a new candidate.

        .. note:: It is forbidden to modify a ballot after voting has
                  started.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm("ballot_data", data)

        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_ballots(rs, (data['id'],)))
            if now() > current['vote_begin']:
                raise ValueError("Unable to modify active ballot.")
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            if len(bdata) > 1:
                ret *= self.sql_update(rs, "assembly.ballots", bdata)
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_changed,
                    current['assembly_id'], additional_info=current['title'])
            if 'candidates' in data:
                existing = set(current['candidates'].keys())
                if not(existing >= {x for x in data['candidates'] if x > 0}):
                    raise ValueError("Non-existing candidates specified.")
                new = {x for x in data['candidates'] if x < 0}
                updated = {x for x in data['candidates']
                           if x > 0 and data['candidates'][x] is not None}
                deleted = {x for x in data['candidates']
                           if x > 0 and data['candidates'][x] is None}
                ## new
                for x in new:
                    new_candidate = copy.deepcopy(data['candidates'][x])
                    new_candidate['ballot_id'] = data['id']
                    ret *= self.sql_insert(rs, "assembly.candidates",
                                           new_candidate)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_added,
                        current['assembly_id'],
                        additional_info=data['candidates'][x]['moniker'])
                ## updated
                for x in updated:
                    update = copy.deepcopy(data['candidates'][x])
                    update['id'] = x
                    ret *= self.sql_update(rs, "assembly.candidates", update)
                    self.assembly_log(
                        rs, const.AssemblyLogCodes.candidate_updated,
                        current['assembly_id'],
                        additional_info=current['candidates'][x]['moniker'])
                ## deleted
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: the id of the new event
        """
        data = affirm("ballot_data", data, creation=True)

        with Atomizer(rs):
            assembly = unwrap(
                self.get_assembly_data(rs, (data['assembly_id'],)))
            if not assembly['is_active']:
                raise ValueError("Assembly already concluded.")
            bdata = {k: v for k, v in data.items() if k in BALLOT_FIELDS}
            ## do a little dance, so that creating a running ballot does not
            ## throw an error
            begin, bdata['vote_begin'] = bdata['vote_begin'], FUTURE_TIMESTAMP
            new_id = self.sql_insert(rs, "assembly.ballots", bdata)
            if 'candidates' in data:
                cdata = {
                    'id': new_id,
                    'candidates': data['candidates'],
                }
                self.set_ballot(rs, cdata)
            ## update voter register
            attendees = self.sql_select(
                rs, "assembly.attendees", ("persona_id",),
                (data['assembly_id'],), entity_key="assembly_id")
            for attendee in attendees:
                entry = {
                    'persona_id': unwrap(attendee),
                    'ballot_id': new_id,
                }
                self.sql_insert(rs, "assembly.voter_register", entry)
            ## fix vote_begin stashed above
            update = {
                'id': new_id,
                'vote_begin': begin,
            }
            self.set_ballot(rs, update)
        self.assembly_log(rs, const.AssemblyLogCodes.ballot_created,
                          data['assembly_id'], additional_info=data['title'])
        return new_id

    @access("assembly_admin")
    def delete_ballot(self, rs, ballot_id):
        """Remove a ballot.

        .. note:: This also removes all associated data (candidates,
          attachments, voter register). As with modification of ballots
          this is forbidden after voting has started.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ballot_id: int
        :rtype: int
        :returns: default return code
        """
        ballot_id = affirm("int", ballot_id)
        ret = 1
        with Atomizer(rs):
            current = unwrap(self.get_ballots(rs, (ballot_id,)))
            if now() > current['vote_begin']:
                raise ValueError("Unable to remove active ballot.")
            if current['bar']:
                deletor = {
                    'id': ballot_id,
                    'bar': None,
                }
                ret *= self.set_ballot(rs, deletor)
            if current['candidates']:
                ret *= self.sql_delete(rs, "assembly.candidates",
                                       current['candidates'].keys())
            self.sql_delete_one(rs, "assembly.voter_register", ballot_id,
                                entity_key="ballot_id")
            self.sql_delete_one(rs, "assembly.attachments", ballot_id,
                                entity_key="ballot_id")
            ret *= self.sql_delete_one(rs, "assembly.ballots", ballot_id)
            self.assembly_log(
                rs, const.AssemblyLogCodes.ballot_deleted,
                current['assembly_id'], additional_info=current['title'])
        return ret

    @access("assembly_user")
    def check_voting_priod_extension(self, rs, ballot_id):
        """Update extension status w.r.t. quorum.

        After the normal voting period has ended an extension is enacted
        if the quorum is not met. The quorum may be zero in which case
        it is automatically met.

        This is an unprivileged operation so it can be done
        automatically by everybody when viewing a ballot. It is not
        allowed to call this before the normal voting period has
        expired.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ballot_id: int
        :rtype: bool
        """
        ballot_id = affirm("int", ballot_id)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            if ballot['extended'] is not None:
                return ballot['extended']
            if now() < ballot['vote_end']:
                raise ValueError("Normal voting still going on.")
            votes = self.sql_select(rs, "assembly.votes", ("id",),
                                    (ballot_id,), entity_key="ballot_id")
            update = {
                'id': ballot_id,
                'extended': len(votes) < ballot['quorum'],
            }
            ## do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            if update['extended']:
                self.assembly_log(
                    rs, const.AssemblyLogCodes.ballot_extended,
                    ballot['assembly_id'], additional_info=ballot['title'])
        return update['extended']

    @access("assembly_user")
    def signup(self, rs, assembly_id):
        """Attend the assembly.

        This does not accept a persona_id on purpose.

        This has to take care to keep the voter register consistent.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int
        :rtype: str or None
        :returns: The secret if a new secret was generated or None if we
          already attend.
        """
        assembly_id = affirm("int", assembly_id)

        with Atomizer(rs):
            if self.does_attend(rs, assembly_id=assembly_id):
                ## already signed up
                return None
            assembly = unwrap(self.get_assembly_data(rs, (assembly_id,)))
            if now() > assembly['signup_end']:
                raise ValueError("Signup already ended.")

            new_attendee = {
                'assembly_id': assembly_id,
                'persona_id': rs.user.persona_id,
                'secret': random_ascii(),
            }
            self.sql_insert(rs, "assembly.attendees", new_attendee)
            self.assembly_log(rs, const.AssemblyLogCodes.new_attendee,
                              assembly_id, persona_id=rs.user.persona_id)
            ## update voter register
            ballots = self.list_ballots(rs, assembly_id)
            for ballot in ballots:
                entry = {
                    'persona_id': rs.user.persona_id,
                    'ballot_id': ballot,
                }
                self.sql_insert(rs, "assembly.voter_register", entry)
            return new_attendee['secret']

    @access("assembly_user")
    def vote(self, rs, ballot_id, vote, secret):
        """Submit a vote.

        This does not accept a persona_id on purpose.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ballot_id: int
        :type vote: str
        :type secret: str or None
        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :rtype: int
        :returns: default return code
        """
        ballot_id = affirm("int", ballot_id)
        secret = affirm("printable_ascii_or_None", secret)

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            vote = affirm("vote", vote, ballot=ballot)
            if not self.does_attend(rs, ballot_id=ballot_id):
                raise ValueError("Must attend to vote.")
            if ballot['extended']:
                reference = ballot['vote_extension_end']
            else:
                reference = ballot['vote_end']
            if now() > reference:
                raise ValueError("Ballot already closed.")
            if now() < ballot['vote_begin']:
                raise ValueError("Ballot not yet open.")

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
                salt = random_ascii()
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

    @access("assembly_user")
    def get_vote(self, rs, ballot_id, secret):
        """Look up a vote.

        This does not accept a persona_id on purpose.

        It is only allowed to call this if we attend the ballot.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ballot_id: int
        :type secret: str or None
        :param secret: The secret of this user. May be None to signal that the
          stored secret should be used.
        :rtype: str or None
        :returns: The vote if we have voted or None otherwise.
        """
        ballot_id = affirm("int", ballot_id)
        secret = affirm("printable_ascii_or_None", secret)

        with Atomizer(rs):
            query = glue("SELECT has_voted FROM assembly.voter_register",
                         "WHERE ballot_id = %s and persona_id = %s")
            has_voted = unwrap(
                self.query_one(rs, query, (ballot_id, rs.user.persona_id)))
            if not has_voted:
                return None
            if secret is None:
                ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
                query = glue("SELECT secret FROM assembly.attendees",
                             "WHERE assembly_id = %s and persona_id = %s")
                secret = unwrap(self.query_one(
                    rs, query, (ballot['assembly_id'], rs.user.persona_id)))
            vote = self.retrieve_vote(rs, ballot_id, secret)
        return vote['vote']

    @access("assembly_user")
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

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ballot_id: int
        :rtype: bool
        :returns: True if a new result file was generated and False if the
          ballot was already tallied.
        """
        ballot_id = affirm("int", ballot_id)

        ## We do not use jinja here as it is currently only used in the
        ## frontend.
        template = string.Template("""{
    "assembly": ${ASSEMBLY},
    "ballot": ${BALLOT},
    "result": ${RESULT},
    "candidates": {
        ${CANDIDATES}
    },
    "bar": ${BAR},
    "voters": [
        ${VOTERS}
    ],
    "votes": [
        ${VOTES}
    ]
}
""")

        with Atomizer(rs):
            ballot = unwrap(self.get_ballots(rs, (ballot_id,)))
            if ballot['is_tallied']:
                return False
            if ballot['extended'] is None:
                raise ValueError("Extension unchecked.")
            if ballot['extended']:
                reference = ballot['vote_extension_end']
            else:
                reference = ballot['vote_end']
            if now() < reference:
                raise ValueError("Voting still going on.")

            votes = self.sql_select(
                rs, "assembly.votes", ("vote", "salt", "hash"), (ballot_id,),
                entity_key="ballot_id")
            result = schulze_evaluate(
                {e['vote'] for e in votes},
                tuple(x['moniker'] for x in ballot['candidates'].values()))
            update = {
                'id': ballot_id,
                'is_tallied': True,
            }
            ## do not use set_ballot since it would throw an error
            self.sql_update(rs, "assembly.ballots", update)
            self.assembly_log(
                rs, const.AssemblyLogCodes.ballot_tallied,
                ballot['assembly_id'], additional_info=ballot['title'])

            ## now generate the result file
            esc = json.dumps
            assembly = unwrap(
                self.get_assembly_data(rs, (ballot['assembly_id'],)))
            candidates = ",\n        ".join(
                "{}: {}".format(esc(c['moniker']), esc(c['description']))
                for c in sorted(ballot['candidates'].values(),
                                key=lambda x: x['moniker']))
            query = glue("SELECT persona_id FROM assembly.voter_register",
                         "WHERE ballot_id = %s and has_voted = True")
            voter_ids = self.query_all(rs, query, (ballot_id,))
            voters = self.core.retrieve_persona_data(
                rs, tuple(unwrap(e) for e in voter_ids))
            voters = ("{} {}".format(e['given_names'], e['family_name'])
                      for e in sorted(voters.values(), key=name_key))
            voter_list = ",\n        ".join(esc(v) for v in voters)
            votes = sorted('{{"vote": {}, "salt": {}, "hash": {}}}'.format(
                esc(v['vote']), esc(v['salt']), esc(v['hash'])) for v in votes)
            vote_list = ",\n        ".join(v for v in votes)
            if ballot['bar']:
                bar = esc(ballot['candidates'][ballot['bar']]['moniker'])
            else:
                bar = esc(None)
            result_file = template.substitute({
                'ASSEMBLY': esc(assembly['title']),
                'BALLOT': esc(ballot['title']),
                'RESULT': esc(result),
                'CANDIDATES': candidates,
                'BAR': bar,
                'VOTERS': voter_list,
                'VOTES': vote_list,})
            path = os.path.join(self.conf.STORAGE_DIR, 'ballot_result',
                                str(ballot_id))
            with open(path, 'w') as f:
                f.write(result_file)
        return True

    @access("assembly_admin")
    def conclude_assembly(self, rs, assembly_id):
        """Do housekeeping after an assembly has ended.

        This mainly purges the secrets which are no longer required for
        updating votes, so that they do not leak in the future.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int
        :rtype: int
        :returns: default return code
        """
        assembly_id = affirm("int", assembly_id)

        with Atomizer(rs):
            assembly = unwrap(self.get_assembly_data(rs, (assembly_id,)))
            if not assembly['is_active']:
                raise ValueError("Assembly not active.")
            ballots = self.get_ballots(rs, self.list_ballots(rs, assembly_id))
            timestamp = now()
            if any((ballot['extended'] is None
                    or timestamp < ballot['vote_end']
                    or (ballot['extended']
                        and timestamp < ballot['vote_extension_end']))
                   for ballot in ballots.values()):
                raise ValueError("Open ballots remain.")
            if timestamp < assembly['signup_end']:
                raise ValueError("Signup still possible.")

            update = {
                'id': assembly_id,
                'is_active': False,
            }
            ret = self.set_assembly_data(rs, update)
            update = {
                'assembly_id': assembly_id,
                'secret': None
            }
            ret *= self.sql_update(rs, "assembly.attendees", update,
                                   entity_key="assembly_id")
            self.assembly_log(rs, const.AssemblyLogCodes.assembly_concluded,
                              assembly_id)
        return ret

    @access("assembly_user")
    def list_attachments(self, rs, *, assembly_id=None, ballot_id=None):
        """List all files attached to an assembly/ballot.

        Files can either be attached to an assembly or ballot, but not
        to both at the same time.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type assembly_id: int or None
        :type ballot_id: int or None
        :rtype: {int: str}
        :returns: dict mapping attachment ids to titles
        """
        if assembly_id is None and ballot_id is None:
            raise ValueError("No input specified.")
        if assembly_id is not None and ballot_id is not None:
            raise ValueError("Too many inputs specified.")
        if assembly_id is not None:
            column = "assembly_id"
            key = affirm("int", assembly_id)
        else:
            column = "ballot_id"
            key = affirm("int", ballot_id)

        data = self.sql_select(rs, "assembly.attachments", ("id", "title"),
                               (key,), entity_key=column)
        return {e['id']: e['title'] for e in data}

    @access("assembly_user")
    @singularize("get_attachment")
    def get_attachments(self, rs, ids):
        """Retrieve data on attachments

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        data = self.sql_select(rs, "assembly.attachments",
                               ASSEMBLY_ATTACHMENT_FIELDS, ids)
        return {e['id']: e for e in data}

    @access("assembly_admin")
    def add_attachment(self, rs, data):
        """Create a new attachment.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: id of the new attachment
        """
        data = affirm("assembly_attachment_data", data)
        if data.get('ballot_id'):
            ballot_data = unwrap(self.get_ballots(rs, (data['ballot_id'],)))
            if now() > ballot_data['vote_begin']:
                raise ValueError("Unable to modify active ballot.")
        ret = self.sql_insert(rs, "assembly.attachments", data)
        assembly_id = data.get('assembly_id')
        if not assembly_id:
            ballot = unwrap(self.get_ballots(rs, (data['ballot_id'],)))
            assembly_id = ballot['assembly_id']
        self.assembly_log(rs, const.AssemblyLogCodes.attachment_added,
                          assembly_id, additional_info=data['title'])
        return ret

    @access("assembly_admin")
    def remove_attachment(self, rs, attachment_id):
        """Delete an attachment.

        .. note:: This only takes care of the entry in the database the
          actual file handling has to be done in the frontend.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type attachment_id: int
        :rtype: int
        :returns: default return code
        """
        attachment_id = affirm("int", attachment_id)
        current = unwrap(self.get_attachments(rs, (attachment_id,)))
        if current['ballot_id']:
            ballot_data = unwrap(self.get_ballots(rs, (current['ballot_id'],)))
            if now() > ballot_data['vote_begin']:
                raise ValueError("Unable to modify active ballot.")
        ret = self.sql_delete_one(rs, "assembly.attachments", attachment_id)
        assembly_id = current['assembly_id']
        if not assembly_id:
            ballot = unwrap(self.get_ballots(rs, (current['ballot_id'],)))
            assembly_id = ballot['assembly_id']
        self.assembly_log(rs, const.AssemblyLogCodes.attachment_removed,
                          assembly_id, additional_info=current['title'])
        return ret

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for congregation services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    assembly_backend = AssemblyBackend(args.configpath)
    conf = Config(args.configpath)
    assembly_server = make_RPCDaemon(assembly_backend, conf.ASSEMBLY_SOCKET,
                                     access_log=conf.ASSEMBLY_ACCESS_LOG)
    run_RPCDaemon(assembly_server, conf.ASSEMBLY_STATE_FILE)
