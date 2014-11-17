#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access_decorator_generator, internal_access_decorator_generator,
    make_RPCDaemon, run_RPCDaemon, affirm_validation as affirm,
    affirm_array_validation as affirm_array, singularize)
from cdedb.common import (glue, PERSONA_DATA_FIELDS, MEMBER_DATA_FIELDS,
                          extract_global_privileges, QuotaException)
from cdedb.query import QueryOperators
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse
import datetime
import logging
import hashlib
import pytz

_LOGGER = logging.getLogger(__name__)

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))

def verify_token(salt, persona_id, current_email, new_email, token):
    """Inverse of :py:func:`cdedb.backend.core.create_token`. See there for
    documentation. Tokens are valid for up to two hours.

    :type salt: str
    :type persona_id: int
    :type current_email: str
    :type new_email: str
    :type token: str
    :rtype: bool
    """
    valid_hashes = []
    for delta in (datetime.timedelta(0), datetime.timedelta(hours=-1)):
        myhash = hashlib.sha512()
        now = datetime.datetime.now(pytz.utc)
        now += delta
        tohash = "{}--{}--{}--{}--{}".format(
            salt, persona_id, current_email, new_email,
            now.strftime("%Y-%m-%d %H"))
        myhash.update(tohash.encode("utf-8"))
        valid_hashes.append(myhash.hexdigest())
    if token in valid_hashes:
        return True
    _LOGGER.debug("Token mismatch ({} not in {}) for {} ({} -> {})".format(
        token, valid_hashes, persona_id, current_email, new_email))
    return False

class CdeBackend(AbstractUserBackend):
    """This is the backend with the most additional role logic."""
    realm = "cde"
    user_management = {
        "data_table" : "cde.member_data",
        "data_fields" : MEMBER_DATA_FIELDS,
        "validator" : "member_data",
    }

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)
        secrets = SecretsConfig(configpath)
        self.verify_token = \
          lambda persona_id, current_email, new_email, token: verify_token(
              secrets.USERNAME_CHANGE_TOKEN_SALT, persona_id, current_email,
              new_email, token)

    @classmethod
    def extract_roles(cls, personadata):
        roles = ["anonymous", "persona"]
        if personadata['status'] in const.CDE_STATI:
            roles.append("user")
        if personadata['status'] in const.MEMBER_STATI:
            roles.append("member")
        if personadata['status'] in const.SEARCHMEMBER_STATI:
            roles.append("searchmember")
        global_privs = extract_global_privileges(personadata["db_privileges"],
                                                 personadata['status'])
        for role in ("cde_admin", "admin"):
            if role in global_privs:
                roles.append(role)
        return roles

    @classmethod
    def db_role(cls, role):
        translate = {
            "anonymous" : "anonymous",
            "persona" : "persona",
            "user" : "member",
            "member" : "member",
            "searchmember" : "member",
            "cde_admin" : "cde_admin",
            "admin" : "admin",
            }
        return "cdb_{}".format(translate[role])

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @staticmethod
    def create_fulltext(data):
        """
        :type data: {str : object}
        :param data: one member data set to convert into a string for fulltext
          search
        :rtype: str
        """
        attrs = (
            "username", "title", "given_names", "display_name",
            "family_name", "birth_name", "name_supplement", "birthday",
            "telephone", "mobile", "address", "address_supplement",
            "postal_code", "location", "country", "address2",
            "address_supplement2", "postal_code2", "location2", "country2",
            "weblink", "specialisation", "affiliation", "timeline",
            "interests", "free_form")
        def _sanitize(val):
            if val is None:
                return ""
            else:
                return str(val)
        vals = (_sanitize(data[x]) for x in attrs)
        return " ".join(vals)

    def set_user_data(self, rs, data, generation, pkeys=None, ukeys=None,
                      allow_username_change=False, may_wait=True,
                      change_note=''):
        """This checks for privileged fields, implements the change log and
        updates the fulltext in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.set_user_data`
        does. If a change requires review it has to be commited using
        :py:meth:`resolve_change` by an administrator.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type generation: int or None
        :param generation: generation on which this request is based, if this
           is not the current generation we abort, may be None to override
           the check
        :type pkeys: [str]
        :param pkeys: keys pretaining to the persona
        :type ukeys: [str]
        :param ukeys: keys pretaining to the user
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
        self.affirm_realm(rs, (data['id'],))

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Permission denied.")
        privileged_fields = {'balance'}
        if set(data) & privileged_fields and not self.is_admin(rs):
            raise RuntimeError("Modifying sensitive key forbidden.")
        if 'username' in data  and not allow_username_change:
            raise RuntimeError("Modification of username prevented.")
        if not may_wait and generation is not None:
            raise ValueError("Non-waiting change without generation override.")

        with Atomizer(rs):
            ## check for race
            current_generation = self.get_generations(rs, (data['id'],))[
                data['id']]
            if generation is not None and current_generation != generation:
                _LOGGER.info("Generation mismatch {} != {} for {}".format(
                    current_generation, generation, data['id']))
                return 0

            ## get current state and check for archived members
            history = self.get_history(rs, data['id'], generations=None)
            current_data = history[current_generation]
            if current_data['status'] == const.PersonaStati.archived_member \
              and data.get('status') not in const.CDE_STATI:
                raise RuntimeError("Editing archived member impossible.")

            ## stash pending change if we may not wait
            diff = None
            if current_data['change_status'] == const.MemberChangeStati.pending \
              and not may_wait:
                old_data = self.get_data(rs, (data['id'],))[data['id']]
                diff = {key : current_data[key] for key in old_data
                        if old_data[key] != current_data[key]}
                current_data = old_data
                query = glue("UPDATE cde.changelog SET change_status = %s",
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
                    query = glue("UPDATE cde.changelog SET change_status = %s",
                                 "WHERE persona_id = %s AND generation = %s")
                    self.query_exec(rs, query, (const.MemberChangeStati.pending,
                                                data['id'], current_generation))
                return 0

            ## determine if something requiring a review changed
            fields_requiring_review = {'birthday', 'family_name', 'given_names'}
            requires_review = (changed_fields & fields_requiring_review
                               and not self.is_admin(rs))

            ## prepare for inserting a new changelog entry
            query = glue("SELECT COUNT(*) AS num FROM cde.changelog",
                         "WHERE persona_id = %s")
            next_generation = self.query_one(
                rs, query, (data['id'],))['num'] + 1
            ## the following is a nop, if there is no pending change
            query = glue("UPDATE cde.changelog SET change_status = %s",
                         "WHERE persona_id = %s AND change_status = %s")
            self.query_exec(rs, query, (
                const.MemberChangeStati.superseded, data['id'],
                const.MemberChangeStati.pending))

            ## insert new changelog entry
            fields = ["submitted_by", "generation", "change_status",
                      "persona_id", "change_note"]
            fields.extend(PERSONA_DATA_FIELDS)
            fields.remove("id")
            fields.extend(MEMBER_DATA_FIELDS)
            query = "INSERT INTO cde.changelog ({}) VALUES ({})".format(
                ", ".join(fields), ", ".join(("%s",) * len(fields)))
            params = [rs.user.persona_id, next_generation,
                      const.MemberChangeStati.pending, data['id'], change_note]
            for field in fields[5:]:
                params.append(data.get(field, current_data[field]))
            self.query_exec(rs, query, params)

            ## resolve change if it doesn't require review
            if not requires_review:
                ret = self.resolve_change(
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
                query = "INSERT INTO cde.changelog ({}) VALUES ({})".format(
                    ", ".join(fields), ", ".join(("%s",) * len(fields)))
                params = [rs.user.persona_id, next_generation + 1,
                          const.MemberChangeStati.pending, data['id'],
                          change_note]
                for field in fields[5:]:
                    if field in diff:
                        params.append(diff[field])
                    elif field in data:
                        params.append(data[field])
                    else:
                        params.append(current_data[field])
                self.query_exec(rs, query, params)

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
        :returns: number of changed entries
        """
        persona_id = affirm("int", persona_id)
        generation = affirm("int", generation)
        ack = affirm("bool", ack)
        allow_username_change = affirm("bool", allow_username_change)
        if not ack:
            query = glue(
                "UPDATE cde.changelog SET reviewed_by = %s, change_status = %s",
                "WHERE persona_id = %s AND change_status = %s",
                "AND generation = %s")
            self.query_exec(rs, query, (
                rs.user.persona_id, const.MemberChangeStati.nacked, persona_id,
                const.MemberChangeStati.pending, generation))
            return 0
        with Atomizer(rs):
            ## look up changelog entry and mark as commited
            history = self.get_history(rs, persona_id,
                                       generations=(generation,))
            data = history[generation]
            if data['change_status'] != const.MemberChangeStati.pending:
                return 0
            query = glue(
                "UPDATE cde.changelog SET {} change_status = %s",
                "WHERE persona_id = %s AND generation = %s").format(
                    "reviewed_by = %s," if reviewed else "")
            params = ((rs.user.persona_id,) if reviewed else tuple()) + (
                const.MemberChangeStati.committed, persona_id, generation)
            self.query_exec(rs, query, params)

            ## determine changed fields
            old_data = self.get_data(rs, (persona_id,))[persona_id]
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
                pdata = {key:data[key] for key in pkeys}
                ret = self.core.set_persona_data(
                    rs, pdata, allow_username_change=allow_username_change)
                if not ret:
                    raise RuntimeError("Modification failed.")
            if len(ukeys) > 0:
                query = glue(
                    "UPDATE cde.member_data SET ({}) = ({})",
                    "WHERE persona_id = %s").format(
                        ", ".join(ukeys), ", ".join(("%s",) * len(ukeys)))
                params = tuple(data[key] for key in ukeys) + (data['id'],)
                ret = self.query_exec(rs, query, params)
                if not ret:
                    raise RuntimeError("Modification failed.")
        if ret > 0:
            with Atomizer(rs):
                new_data = self.retrieve_user_data(rs, (data['id'],))[
                    data['id']]
                text = self.create_fulltext(new_data)
                query = glue("UPDATE cde.member_data SET fulltext = %s",
                             "WHERE persona_id = %s")
                self.query_exec(rs, query, (text, data['id']))
        return ret

    @access("user")
    def change_user(self, rs, data, generation, may_wait=True, change_note=''):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type may_wait: bool
        :param may_wait: override for system requests (which may not wait)
        :type change_note: str
        :param change_note: Descriptive line for changelog
        :rtype: int
        :returns: number of users changed
        """
        data = affirm("member_data", data)
        generation = affirm("int_or_None", generation)
        return self.set_user_data(rs, data, generation, may_wait=may_wait,
                                  change_note=change_note)

    @access("user")
    @singularize("get_data_single_no_quota")
    def get_data_no_quota(self, rs, ids):
        """This behaves like
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data`, that is
        it does not check or update the quota.

        This is intended for consumption by the event backend, where
        orgas will need access. This should only be used after serious
        consideration. This is a separate function (and not a mere
        parameter to :py:meth:`get_data`) so that its usage can be
        tracked.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : {str : object}}
        :returns: dict mapping ids to requested data
        """
        return super().get_data(rs, ids)

    @access("user")
    @singularize("get_data_single")
    def get_data(self, rs, ids):
        """This checks for quota in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data` does.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : {str : object}}
        :returns: dict mapping ids to requested data
        """
        ids = affirm_array("int", ids)
        with Atomizer(rs):
            query = glue("SELECT queries FROM core.quota WHERE persona_id = %s",
                         "AND qdate = %s")
            today = datetime.datetime.now().date()
            num = self.query_one(rs, query, (rs.user.persona_id, today))
            query = glue("UPDATE core.quota SET queries = %s",
                         "WHERE persona_id = %s AND qdate = %s")
            if num is None:
                query = glue("INSERT INTO core.quota",
                             "(queries, persona_id, qdate) VALUES (%s, %s, %s)")
                num = 0
            else:
                num = num['queries']
            new = tuple(i == rs.user.persona_id for i in ids).count(False)
            if num + new > self.conf.MAX_QUERIES_PER_DAY \
              and not self.is_admin(rs):
                raise QuotaException("Too many queries.")
            self.query_exec(rs, query, (num + new, rs.user.persona_id, today))
        return self.retrieve_user_data(rs, ids)

    @access("user")
    @singularize("get_generation")
    def get_generations(self, rs, ids):
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : int}
        :returns: dict mapping ids to generations
        """
        ids = affirm_array("int", ids)
        query = glue("SELECT persona_id, max(generation) AS generation",
                     "FROM cde.changelog WHERE persona_id = ANY(%s)",
                     "AND change_status = ANY(%s) GROUP BY persona_id")
        valid_status = (const.MemberChangeStati.pending,
                        const.MemberChangeStati.committed)
        data = self.query_all(rs, query, (ids, valid_status))
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {e['persona_id'] : e['generation'] for e in data}

    @access("cde_admin")
    def get_pending_changes(self, rs):
        """Retrive currently pending changes in the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :rtype: {int : {str : object}}
        :returns: dict mapping persona ids to dicts containing information
          about the change and the persona
        """
        query = glue("SELECT persona_id, given_names, family_name, generation",
                     "FROM cde.changelog WHERE change_status = %s")
        data = self.query_all(rs, query, (const.MemberChangeStati.pending,))
        return {e['persona_id'] : e for e in data}

    @access("cde_admin")
    def get_history(self, rs, anid, generations):
        """Retrieve history of a member data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type anid: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int : {str : object}}
        :returns: mapping generation to data set
        """
        anid = affirm("int", anid)
        if generations is not None:
            generations = affirm_array("int", generations)
        fields = list(PERSONA_DATA_FIELDS)
        fields.remove("id")
        fields.append("persona_id AS id")
        fields.extend(MEMBER_DATA_FIELDS)
        fields.extend(("submitted_by", "reviewed_by", "cdate", "generation",
                       "change_status"))
        query = "SELECT {} FROM cde.changelog WHERE persona_id = %s".format(
            ", ".join(fields))
        params = [anid]
        if generations is not None:
            query = glue(query, "AND generation = ANY(%s)")
            params.append(generations)
        data = self.query_all(rs, query, params)
        return {e['generation'] : e for e in data}

    @access("persona")
    def change_username(self, rs, persona_id, new_username, token):
        """Since usernames are used for login, this needs a bit of
        care. Normally this would be placed in the core backend, but to
        implement the changelog functionality this is moved to the cde
        realm.


        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type persona_id: int
        :type new_username: str
        :type token: str
        :rtype: (bool, str)
        """
        persona_id = affirm("int", persona_id)
        new_username = affirm("email", new_username)
        token = affirm("str", token)
        with Atomizer(rs):
            if self.core.verify_existence(rs, new_username):
                ## abort if there is allready an account with this address
                return False, "Name collision."
            is_cde = self.core.get_realm(rs, persona_id) == "cde"
            query = "SELECT username FROM core.personas WHERE id = %s"
            data = self.query_one(rs, query, (persona_id,))
            if self.verify_token(persona_id, data['username'], new_username,
                                 token):
                new_data = {
                    'id' : persona_id,
                    'username' : new_username,
                }
                if is_cde:
                    if self.set_user_data(rs, new_data, generation=None,
                                          allow_username_change=True,
                                          may_wait=False):
                        return True, new_username
                else:
                    if self.core.set_persona_data(rs, new_data,
                                                  allow_username_change=True):
                        return True, new_username
        return False, "Failed."

    @access("user")
    @singularize("get_foto")
    def get_fotos(self, rs, ids):
        """Retrieve the profile picture attribute.

        This is separate since it is not logged in the changelog and
        hence not present in :py:data:`cdedb.common.MEMBER_DATA_FIELDS`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : str}
        """
        ids = affirm_array("int", ids)
        query = glue("SELECT persona_id, foto FROM cde.member_data",
                     "WHERE persona_id = ANY(%s)")
        data = self.query_all(rs, query, (ids,))
        if len(data) != len(ids):
            raise RuntimeError("Invalid ids requested.")
        return {e['persona_id'] : e['foto'] for e in data}

    @access("user")
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
            raise RuntimeError("Permission denied.")
        query = "UPDATE cde.member_data SET foto = %s WHERE persona_id = %s"
        num = self.query_exec(rs, query, (foto, persona_id))
        return bool(num)

    @access("user")
    def foto_usage(self, rs, foto):
        """Retrieve usage number for a specific foto.

        So we know when a foto is up for garbage collection.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type foto: str
        :rtype: int
        """
        foto = affirm("str", foto)
        query = "SELECT COUNT(*) AS num FROM cde.member_data WHERE foto = %s"
        data = self.query_one(rs, query, (foto,))
        return data['num']

    @access("searchmember")
    def submit_general_query(self, rs, query):
        """Realm specific wrapper around
        :py:meth:`cdedb.backend.common.AbstractBackend.general_query`.`

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type query: :py:class:`cdedb.query.Query`
        :rtype: [{str : obj}]
        """
        query = affirm("serialized_query", query)
        if query.scope == "qview_cde_member":
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.SEARCHMEMBER_STATI))
            query.spec['status'] = "int"
        elif query.scope == "qview_cde_user":
            if not self.is_admin(rs):
                raise RuntimeError("Permission denied.")
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.CDE_STATI))
        elif query.scope == "qview_cde_archived_user":
            if not self.is_admin(rs):
                raise RuntimeError("Permission denied.")
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
    cde_backend = CdeBackend(args.configpath)
    conf = Config(args.configpath)
    cde_server = make_RPCDaemon(cde_backend, conf.CDE_SOCKET,
                                access_log=conf.CDE_ACCESS_LOG)
    run_RPCDaemon(cde_server, conf.CDE_STATE_FILE)
