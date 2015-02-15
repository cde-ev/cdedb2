#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize, create_fulltext)
from cdedb.common import (
    glue, PERSONA_DATA_FIELDS, MEMBER_DATA_FIELDS, QuotaException, merge_dicts,
    PrivilegeError)
from cdedb.query import QueryOperators
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse
import datetime
import logging
import decimal
import pytz

_LOGGER = logging.getLogger(__name__)

class CdEBackend(AbstractUserBackend):
    """This is the backend with the most additional role logic.

    .. note:: The changelog functionality is to be found in the core backend.
    """
    realm = "cde"
    user_management = {
        "data_table": "cde.member_data",
        "data_fields": MEMBER_DATA_FIELDS,
        "validator": "member_data",
        "user_status": const.PersonaStati.member,
    }

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        super().__init__(configpath)

    def establish(self, sessionkey, method, allow_internal=False):
        return super().establish(sessionkey, method,
                                 allow_internal=allow_internal)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def set_user_data(self, rs, data, generation, allow_username_change=False,
                      may_wait=True, change_note=''):
        """This checks for privileged fields, implements the change log and
        updates the fulltext in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.set_user_data`
        does. If a change requires review it has to be committed using
        :py:meth:`resolve_change` by an administrator.

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
        self.affirm_realm(rs, (data['id'],))

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")
        privileged_fields = {'balance'}
        if set(data) & privileged_fields and not self.is_admin(rs):
            raise PrivilegeError("Modifying sensitive key forbidden.")
        if 'username' in data  and not allow_username_change:
            raise RuntimeError("Modification of username prevented.")
        if not may_wait and generation is not None:
            raise ValueError("Non-waiting change without generation override.")

        return self.core.changelog_submit_change(
            rs, data, generation, allow_username_change=allow_username_change,
            may_wait=may_wait, change_note=change_note)

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

        return self.core.changelog_resolve_change(
            rs, persona_id, generation, ack,
            allow_username_change=allow_username_change, reviewed=reviewed)

    @access("formermember")
    def change_user(self, rs, data, generation, may_wait=True,
                    change_note=None):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :type may_wait: bool
        :param may_wait: override for system requests (which may not wait)
        :type change_note: str
        :param change_note: Descriptive line for changelog
        :rtype: int
        :returns: number of users changed
        """
        data = affirm("member_data", data)
        generation = affirm("int_or_None", generation)
        may_wait = affirm("bool", may_wait)
        change_note = affirm("str_or_None", change_note)
        if change_note is None:
            self.logger.info("No change note specified (persona_id={}).".format(
                data['id']))
            change_note = "Unspecified change."

        return self.set_user_data(rs, data, generation, may_wait=may_wait,
                                  change_note=change_note)

    @access("event_user")
    @singularize("get_data_no_quota_one")
    def get_data_no_quota(self, rs, ids):
        """This behaves like
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data`, that is
        it does not check or update the quota.

        This is intended for consumption by the event backend, where
        orgas will need access. This should only be used after serious
        consideration. This is a separate function (and not a mere
        parameter to :py:meth:`get_data`) so that its usage can be
        tracked.

        This escalates privileges so non-member orgas are able to utilize
        the administrative interfaces to an event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        orig_conn = None
        if not rs.user.is_member:
            if rs.conn.is_contaminated:
                raise RuntimeError("Atomized -- impossible to escalate.")
            orig_conn = rs.conn
            rs.conn = self.connpool['cdb_member']
        ret = super().get_data(rs, ids)
        if orig_conn:
            rs.conn = orig_conn
        return ret

    @access("formermember")
    @singularize("get_data_outline_one")
    def get_data_outline(self, rs, ids):
        """This is a restricted version of :py:meth:`get_data`.

        It does not incorporate quotas, but returns only a limited
        number of attributes.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        ret = super().get_data(rs, ids)
        fields = ("id", "username", "display_name", "status", "family_name",
                  "given_names", "title", "name_supplement")
        return {key: {k: v for k, v in value.items() if k in fields}
                for key, value in ret.items()}

    @access("formermember")
    @singularize("get_data_one")
    def get_data(self, rs, ids):
        """This checks for quota in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data` does.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        ids = affirm_array("int", ids)

        with Atomizer(rs):
            query = glue("SELECT queries FROM core.quota WHERE persona_id = %s",
                         "AND qdate = %s")
            today = datetime.datetime.now(pytz.utc).date()
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
            if (num + new > self.conf.MAX_QUERIES_PER_DAY
                    and not self.is_admin(rs)):
                raise QuotaException("Too many queries.")
            self.query_exec(rs, query, (num + new, rs.user.persona_id, today))
        return self.retrieve_user_data(rs, ids)

    @access("cde_admin")
    def create_user(self, rs, data, change_note="Member creation."):
        """Make a new member account.

        This caters to the cde realm specifics, foremost the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        data = affirm("member_data", data, creation=True)
        change_note = affirm("str", change_note)
        ## insert default for optional and non-settable fields for changelog
        update = {
            'balance': decimal.Decimal(0),
            'decided_search': False,
            'bub_search': False,
        }
        merge_dicts(data, update)

        keys = tuple(key for key in data if key in MEMBER_DATA_FIELDS)
        fulltext = create_fulltext(data)
        query = "INSERT INTO {} ({}) VALUES ({})".format(
            "cde.member_data",
            ", ".join(("persona_id", "fulltext") + keys),
            ", ".join(("%s",) * (2+len(keys))))

        with Atomizer(rs):
            new_id = self.core.create_persona(rs, data)
            params = (new_id, fulltext) + tuple(data[key] for key in keys)
            self.query_exec(rs, query, params)
            fields = ["submitted_by", "generation", "change_status",
                      "persona_id", "change_note"]
            fields.extend(PERSONA_DATA_FIELDS)
            fields.remove("id")
            fields.extend(MEMBER_DATA_FIELDS)
            query = "INSERT INTO core.changelog ({}) VALUES ({})".format(
                ", ".join(fields), ", ".join(("%s",) * len(fields)))
            params = [rs.user.persona_id, 1,
                      const.MemberChangeStati.committed, new_id, change_note]
            for field in fields[5:]:
                params.append(data.get(field))
            self.query_exec(rs, query, params)
        return new_id

    def genesis_check(self, rs, case_id, secret, username=None):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available for cde realm.")

    def genesis(self, rs, case_id, secret, data):
        """Member accounts cannot be requested."""
        raise NotImplementedError("Not available for cde realm.")

    @access("formermember")
    @singularize("get_generation")
    def get_generations(self, rs, ids):
        """Retrieve the current generation of the persona ids in the
        changelog. This includes committed and pending changelog entries.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: int}
        :returns: dict mapping ids to generations
        """
        ids = affirm_array("int", ids)

        return self.core.changelog_get_generations(rs, ids)

    @access("cde_admin")
    def get_changes(self, rs, stati):
        """Retrive changes in the changelog.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type stati: [int]
        :param stati: limit changes to those with a status in this
        :rtype: {int: {str: object}}
        :returns: dict mapping persona ids to dicts containing information
          about the change and the persona
        """
        affirm_array("int", stati)
        return self.core.changelog_get_changes(rs, stati)

    @access("cde_admin")
    def get_history(self, rs, anid, generations):
        """Retrieve history of a member data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type anid: int
        :type generations: [int] or None
        :parameter generations: generations to retrieve, all if None
        :rtype: {int: {str: object}}
        :returns: mapping generation to data set
        """
        anid = affirm("int", anid)
        if generations is not None:
            generations = affirm_array("int", generations)

        return self.core.changelog_get_history(rs, anid, generations)

    @access("formermember")
    @singularize("get_foto")
    def get_fotos(self, rs, ids):
        """Retrieve the profile picture attribute.

        This is separate since it is not logged in the changelog and
        hence not present in :py:data:`cdedb.common.MEMBER_DATA_FIELDS`.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: str}
        """
        ids = affirm_array("int", ids)
        query = glue("SELECT persona_id, foto FROM cde.member_data",
                     "WHERE persona_id = ANY(%s)")
        data = self.query_all(rs, query, (ids,))
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {e['persona_id']: e['foto'] for e in data}

    @access("formermember")
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
            raise PrivilegeError("Not privileged.")
        query = "UPDATE cde.member_data SET foto = %s WHERE persona_id = %s"
        num = self.query_exec(rs, query, (foto, persona_id))
        return bool(num)

    @access("formermember")
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
        :rtype: [{str: object}]
        """
        query = affirm("serialized_query", query)
        if query.scope == "qview_cde_member":
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.SEARCHMEMBER_STATI))
            query.spec['status'] = "int"
        elif query.scope == "qview_cde_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
            query.constraints.append(("status", QueryOperators.oneof,
                                      const.CDE_STATI))
        elif query.scope == "qview_cde_archived_user":
            if not self.is_admin(rs):
                raise PrivilegeError("Admin only.")
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
    cde_backend = CdEBackend(args.configpath)
    conf = Config(args.configpath)
    cde_server = make_RPCDaemon(cde_backend, conf.CDE_SOCKET,
                                access_log=conf.CDE_ACCESS_LOG)
    run_RPCDaemon(cde_server, conf.CDE_STATE_FILE)
