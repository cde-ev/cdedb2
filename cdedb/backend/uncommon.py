#!/usr/bin/env python3

"""More common infrastructure for the backend services.

This provides :py:class:`AbstractUserBackend` and should technically be
a part of :py:mod:`cdedb.backend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.database.connection import Atomizer
from cdedb.common import glue, PERSONA_DATA_FIELDS, PrivilegeError
from cdedb.backend.core import CoreBackend
from cdedb.backend.common import (
    AbstractBackend, AuthShim, affirm_validation as affirm,
    affirm_array_validation as affirm_array)
import cdedb.database.constants as const
import abc

class AbstractUserBackend(AbstractBackend, metaclass=abc.ABCMeta):
    """Template for backends which manage their own kind of users.

    This is basically every backend with exception of 'core' and 'session'.
    """
    #: Specification how user management works. To be filled by child classes.
    user_management = {
        "data_table": None, ## str
        "data_fields": None, ## [str], does not contain PERSONA_DATA_FIELDS
        "validator": None, ## str
        "user_status": None, ## int, one of const.PersonaStati
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.core = AuthShim(CoreBackend(configpath))

    def affirm_realm(self, rs, ids, realms=None):
        """Check that all personas corresponding to the ids are in the
        appropriate realm.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :type realms: {str}
        :param realms: Set of realms to check for. By default this is
          the set containing only the realm of this class.
        """
        realms = realms or {self.realm}
        if (ids,) == (rs.user.persona_id,):
            actual_realms = {rs.user.realm}
        else:
            actual_realms = set(self.core.get_realms(rs, ids).values())
        if not actual_realms <= realms:
            raise ValueError("Wrong realm for personas.")

    def retrieve_user_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        :returns: dict mapping ids to requested data
        """
        if not self.user_management['data_table']:
            return self.core.retrieve_persona_data(rs, ids)
        else:
            table = "{} AS u JOIN core.personas AS p ON u.persona_id = p.id"
            table = table.format(self.user_management['data_table'])
            data = self.sql_select(
                rs, table,
                PERSONA_DATA_FIELDS + self.user_management['data_fields'], ids,
                entity_key="p.id")
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {d['id']: d for d in data}

    def set_user_data(self, rs, data):
        """Update some keys of a data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        self.affirm_realm(rs, (data['id'],))
        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise PrivilegeError("Not privileged.")

        if not self.user_management['data_table']:
            return self.core.set_persona_data(rs, data)
        else:
            pdata = {k: v for k, v in data.items() if k in PERSONA_DATA_FIELDS}
            udata = {k: v for k, v in data.items()
                     if k in self.user_management['data_fields']}
            udata['persona_id'] = pdata['id']
            ret = 1
            with Atomizer(rs):
                if len(pdata) > 1:
                    ret *= self.core.set_persona_data(rs, pdata)
                if len(udata) > 1:
                    ret *= self.sql_update(
                        rs, self.user_management['data_table'], udata,
                        entity_key="persona_id")
                if not ret:
                    raise RuntimeError("Modification failed.")
            return ret

    ## @access("realm_user")
    @abc.abstractmethod
    def change_user(self, rs, data):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: default return code
        """
        data = affirm(self.user_management['validator'], data)
        return self.set_user_data(rs, data)

    ## @access("realm_user")
    ## @singularize("get_data_one")
    @abc.abstractmethod
    def get_data(self, rs, ids):
        """Aquire data sets for specified ids.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {str: object}}
        """
        ids = affirm_array("int", ids)
        return self.retrieve_user_data(rs, ids)

    ## @access("realm_admin")
    @abc.abstractmethod
    def create_user(self, rs, data):
        """Make a new account.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        data = affirm(self.user_management['validator'], data,
                      creation=True)

        with Atomizer(rs):
            new_id = self.core.create_persona(rs, data)
            num = 1
            if self.user_management['data_fields']:
                udata = {k: v for k, v in data.items()
                         if k in self.user_management['data_fields']}
                udata['persona_id'] = new_id
                num = self.sql_insert(
                    rs, self.user_management['data_table'], udata,
                    entity_key="persona_id")
            if not (num and new_id):
                raise RuntimeError("User creation failed.")
            return new_id

    ## @access("anonymous")
    @abc.abstractmethod
    def genesis_check(self, rs, case_id, secret):
        """Verify input data for genesis case.

        This is a security check, which enables us to share a
        non-ephemeral private link after a moderator approved a request.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type case_id: int
        :type secret: str
        :rtype: bool
        """
        case_id = affirm("int", case_id)
        secret = affirm("str", secret)
        query = glue("SELECT case_status, secret, persona_status",
                     "FROM core.genesis_cases WHERE id = %s")
        case = self.query_one(rs, query, (case_id,))
        return (bool(case)
                and case['case_status'] == const.GenesisStati.approved
                and case['secret'] == secret
                and (case['persona_status']
                     == self.user_management['user_status']))

    ## @access("anonymous")
    @abc.abstractmethod
    def genesis(self, rs, case_id, secret, data):
        """Create a new user account upon request.

        This is the final step in the genesis process and actually creates
        the account. This heavily escalates privileges to allow the creation
        of a user with an anonymous role.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type case_id: int
        :type secret: str
        :param secret: Verification for the authenticity of the invocation.
        :type data: {str: object}
        :rtype: int
        :returns: The id of the newly created persona.
        """
        case_id = affirm("int", case_id)
        secret = affirm("str", secret)
        data = affirm(self.user_management['validator'], data,
                      creation=True)

        ## escalate priviliges
        if rs.conn.is_contaminated:
            raise RuntimeError("Atomized -- impossible to escalate.")
        orig_conn = rs.conn
        rs.conn = self.connpool['cdb_admin']
        orig_roles = rs.user.roles
        rs.user.roles = rs.user.roles | {"core_admin",
                                         "{}_admin".format(self.realm)}

        with Atomizer(rs):
            case = self.sql_select_one(
                rs, "core.genesis_cases",
                ("username", "given_names", "family_name", "case_status",
                 "persona_status", "secret"), case_id)
            if not case or case['secret'] != secret:
                return None, "Invalid case."
            if case['case_status'] != const.GenesisStati.approved:
                return None, "Invalid state."
            if case['persona_status'] != self.user_management['user_status']:
                return None, "Invalid realm."
            data['username'] = case['username']
            data['given_names'] = case['given_names']
            data['family_name'] = case['family_name']
            ret = self.create_user(rs, data)
            update = {
                'id': case_id,
                'case_status': const.GenesisStati.finished,
            }
            num = self.sql_update(rs, "core.genesis_cases", update)
            if not num:
                raise RuntimeError("Closing case failed.")

        ## deescalate privileges
        rs.conn = orig_conn
        rs.user.roles = orig_roles
        return ret
