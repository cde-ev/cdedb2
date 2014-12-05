#!/usr/bin/env python3

"""More common infrastructure for the backend services.

This provides :py:class:`AbstractUserBackend` and should technically be
a part of :py:mod:`cdedb.backend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.database.connection import Atomizer
from cdedb.common import glue, PERSONA_DATA_FIELDS
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
        query = glue(
            "SELECT {} FROM {} AS u JOIN core.personas AS p",
            "ON u.persona_id = p.id WHERE p.id = ANY(%s)").format(
                ", ".join(PERSONA_DATA_FIELDS +
                          self.user_management['data_fields']),
                self.user_management['data_table'])
        data = self.query_all(rs, query, (ids,))
        if len(data) != len(ids):
            raise ValueError("Invalid ids requested.")
        return {d['id']: d for d in data}

    def set_user_data(self, rs, data):
        """Update some keys of a data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str: object}
        :rtype: int
        :returns: number of changed entries
        """
        self.affirm_realm(rs, (data['id'],))

        pkeys = tuple(key for key in data if key in PERSONA_DATA_FIELDS)
        ukeys = tuple(key for key in data
                      if key in self.user_management['data_fields'])

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Not enough privileges.")

        pdata = {key:data[key] for key in pkeys}
        ret = 0
        with Atomizer(rs):
            if len(pkeys) > 1:
                ret = self.core.set_persona_data(rs, pdata)
                if not ret:
                    raise RuntimeError("Modification failed.")
            if len(ukeys) > 0:
                query = "UPDATE {} SET ({}) = ({}) WHERE persona_id = %s"
                query = query.format(
                    self.user_management['data_table'], ", ".join(ukeys),
                    ", ".join(("%s",) * len(ukeys)))
                params = tuple(data[key] for key in ukeys) + (data['id'],)
                ret = self.query_exec(rs, query, params)
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
        :returns: number of users changed
        """
        data = affirm(self.user_management['validator'], data)
        return self.set_user_data(rs, data)

    ## @access("realm_user")
    ## @singularize("get_data_single")
    @abc.abstractmethod
    def get_data(self, rs, ids):
        """Aquire data sets for specified ids.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str: object}]
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
                      initialization=True)

        keys = tuple(key for key in data
                     if key in self.user_management['data_fields'])
        query = "INSERT INTO {} ({}) VALUES ({})".format(
            self.user_management['data_table'],
            ", ".join(("persona_id",) + keys),
            ", ".join(("%s",) * (1+len(keys))))
        with Atomizer(rs):
            new_id = self.core.create_persona(rs, data)
            params = (new_id,) + tuple(data[key] for key in keys)
            num = self.query_exec(rs, query, params)
            if not num:
                raise RuntimeError("Modification failed.")
        return new_id

    ## @access("anonymous")
    @abc.abstractmethod
    def genesis_check(self, rs, case_id, secret, username=None):
        """Verify input data for genesis case.

        This is a security check, which enables us to share a
        non-ephemeral private link after a moderator approved a request.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type case_id: int
        :type secret: str
        :type username: str or None
        :param username: If provided this is checked against the deposited
            email address.
        :rtype: bool
        """
        case_id = affirm("int", case_id)
        secret = affirm("str", secret)
        if username is not None:
            username = affirm("email", username)
        query = glue("SELECT case_status, secret, persona_status, username",
                     "FROM core.genesis_cases WHERE id = %s")
        case = self.query_one(rs, query, (case_id,))
        return (bool(case)
                and case['case_status'] == const.GenesisStati.approved
                and case['secret'] == secret
                and (case['persona_status']
                     == self.user_management['user_status'])
                and (username is None or username == case['username']))

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
                      initialization=True)

        query = glue("SELECT username, case_status, persona_status, secret",
                     "FROM core.genesis_cases WHERE id = %s")

        ## escalate priviliges
        if rs.conn.is_contaminated:
            raise RuntimeError("Atomized -- impossible to escalate.")
        orig_conn = rs.conn
        rs.conn = self.connpool['cdb_admin']
        orig_roles = rs.user.roles
        rs.user.roles = rs.user.roles | {"core_admin",
                                         "{}_admin".format(self.realm)}

        with Atomizer(rs):
            case = self.query_one(rs, query, (case_id,))
            if not case or case['secret'] != secret:
                return None, "Invalid case."
            if case['case_status'] != const.GenesisStati.approved:
                return None, "Invalid state."
            if case['persona_status'] != self.user_management['user_status']:
                return None, "Invalid realm."
            if data['username'] != case['username']:
                return None, "Mismatched username."
            ## this elevates privileges
            ret = self.create_user(rs, data)
            query = glue("UPDATE core.genesis_cases SET case_status = %s",
                         "WHERE id = %s")
            self.query_exec(rs, query, (const.GenesisStati.finished, case_id))

        ## deescalate privileges
        rs.conn = orig_conn
        rs.user.roles = orig_roles
        return ret
