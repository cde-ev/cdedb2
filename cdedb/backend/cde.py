#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

from cdedb.backend.common import AbstractBackend, access_decorator_generator, \
     internal_access_decorator_generator, make_RPCDaemon, \
     run_RPCDaemon, AuthShim
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import glue, PERSONA_DATA_FIELDS_MOD, PERSONA_DATA_FIELDS, \
     MEMBER_DATA_FIELDS, extract_global_privileges, extract_realm
from cdedb.config import Config
from cdedb.backend.core import CoreBackend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))

class CdeBackend(AbstractBackend):
    """This is the backend with the most additional role logic."""
    realm = "cde"

    def __init__(self, configpath):
        super().__init__(configpath)
        self.core = AuthShim(CoreBackend(configpath))

    @classmethod
    def extract_roles(cls, personadata):
        roles = ["anonymous", "persona"]
        if personadata["status"] in const.CDE_STATUSES:
            roles.append("user")
        if personadata["status"] in const.MEMBER_STATUSES:
            roles.append("member")
        if personadata["status"] in const.SEARCHMEMBER_STATUSES:
            roles.append("searchmember")
        global_privs = extract_global_privileges(personadata["db_privileges"],
                                                 personadata["status"])
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

    def retrieve_member_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        query = glue(
            "SELECT {} FROM cde.member_data AS m JOIN core.personas",
            "AS p ON m.persona_id = p.id WHERE p.id = ANY(%s)").format(
                ", ".join(PERSONA_DATA_FIELDS + MEMBER_DATA_FIELDS))

        # TODO add academy information

        ret = self.query_all(rs, query, (ids,))
        if len(ret) != len(ids):
            raise ValueError("Invalid ids requested.")
        return ret

    def set_complete_member_data(self, rs, data):
        """This requires that all possible keys are present. Often you may
        want to use :py:meth:`set_member_data` instead.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of changed entries
        """
        return self.set_member_data(rs, data, pkeys=PERSONA_DATA_FIELDS_MOD,
                                    mkeys=MEMBER_DATA_FIELDS)

    def set_member_data(self, rs, data, pkeys=None, mkeys=None):
        """Update only some keys of a data set. If ``pkeys`` or ``mkeys`` is not
        passed all keys available in ``data`` are updated.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type pkeys: [str]
        :param pkeys: keys pretaining to the persona
        :type mkeys: [str]
        :param mkeys: keys pretaining to the member
        :rtype: int
        :returns: number of changed entries
        """
        realm = None
        if data['id'] == rs.user.persona_id:
            realm = rs.user.realm
        else:
            query = "SELECT status FROM core.personas WHERE id = %s"
            d = self.query_one(rs, query, (data['id'],))
            if not d:
                raise ValueError("Nonexistant user.")
            realm = extract_realm(d['status'])
        if realm != self.realm:
            raise ValueError("Wrong realm for persona.")

        if not pkeys:
            pkeys = tuple(key for key in data if key in PERSONA_DATA_FIELDS)
        if not mkeys:
            mkeys = tuple(key for key in data if key in MEMBER_DATA_FIELDS)

        # TODO add changelog functionality

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Permission denied")
        privileged_fields = set(('balance',))
        if (set(data) & privileged_fields) and not self.is_admin(rs):
            raise RuntimeError("Modifying sensitive key forbidden.")

        pdata = {key:data[key] for key in pkeys}
        with Atomizer(rs):
            self.core.set_persona_data(rs, pdata)
            query = glue("UPDATE cde.member_data SET ({}) = ({})",
                         "WHERE persona_id = %s").format(
                             ", ".join(mkeys), ", ".join(("%s",) * len(mkeys)))
            return self.query_exec(
                rs, query, tuple(data[key] for key in mkeys) + (data['id'],))

        # TODO update fulltext

    @access("user")
    def change_member(self, rs, data):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of members changed
        """
        data = affirm("member_data", data)
        self.set_member_data(rs, data)

    @access("user")
    def get_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        # TODO add quota functionality
        return self.retrieve_member_data(rs, ids)

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
