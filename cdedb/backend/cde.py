#!/usr/bin/env python3

"""The CdE backend provides services for members and also former members
(which attain the ``user`` role) as well as facilities for managing the
organization. We will speak of members in most contexts where former
members are also possible.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import access_decorator_generator, \
    internal_access_decorator_generator, make_RPCDaemon, run_RPCDaemon, \
    affirm_validation as affirm, affirm_array_validation as affirm_array
from cdedb.common import glue, PERSONA_DATA_FIELDS, MEMBER_DATA_FIELDS, \
    extract_global_privileges, QuotaException
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
import argparse
import datetime

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "user", "member", "searchmember", "cde_admin",
     "admin"))

class CdeBackend(AbstractUserBackend):
    """This is the backend with the most additional role logic."""
    realm = "cde"
    user_management = {
        "data_table" : "cde.member_data",
        "data_fields" : MEMBER_DATA_FIELDS,
        "validator" : "member_data",
    }

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

    def set_user_data(self, rs, data, pkeys=None, ukeys=None):
        """This checks for privileged fields, implements the change log
        and updates the fulltext in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.set_user_data`
        does.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type pkeys: [str]
        :param pkeys: keys pretaining to the persona
        :type ukeys: [str]
        :param ukeys: keys pretaining to the user
        :rtype: int
        :returns: number of changed entries
        """
        self.affirm_realm(rs, (data['id'],))

        if not pkeys:
            pkeys = tuple(key for key in data if key in PERSONA_DATA_FIELDS)
        if not ukeys:
            ukeys = tuple(key for key in data if key in MEMBER_DATA_FIELDS)

        # TODO add changelog functionality

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Permission denied")
        privileged_fields = {'balance'}
        if (set(data) & privileged_fields) and not self.is_admin(rs):
            raise RuntimeError("Modifying sensitive key forbidden.")

        pdata = {key:data[key] for key in pkeys}
        with Atomizer(rs):
            self.core.set_persona_data(rs, pdata)
            query = glue("UPDATE cde.member_data SET ({}) = ({})",
                         "WHERE persona_id = %s").format(
                             ", ".join(ukeys), ", ".join(("%s",) * len(ukeys)))
            ret = self.query_exec(
                rs, query, tuple(data[key] for key in ukeys) + (data['id'],))

        with Atomizer(rs):
            new_data = self.retrieve_user_data(rs, (data['id'],))[0]
            text = self.create_fulltext(new_data)
            query = glue("UPDATE cde.member_data SET fulltext = %s",
                         "WHERE persona_id = %s")
            self.query_exec(rs, query, (text, data['id']))
        return ret

    @access("user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("user")
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
        :rtype: [{str : object}]
        """
        return super().get_data(rs, ids)

    @access("user")
    def get_data(self, rs, ids):
        """This checks for quota in addition to what
        :py:meth:`cdedb.backend.common.AbstractUserBackend.get_data` does.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
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
