#!/usr/bin/env python3

"""More common infrastructure for the backend services.

This provides :py:class:`AbstractUserBackend` and should technically be
a part of :py:mod:`cdedb.backend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.database.connection import Atomizer
from cdedb.common import glue, PERSONA_DATA_FIELDS, PERSONA_DATA_FIELDS_MOD
from cdedb.backend.core import CoreBackend
from cdedb.backend.common import AbstractBackend, AuthShim, \
    affirm_validation as affirm, affirm_array_validation as affirm_array
import abc

class AbstractUserBackend(AbstractBackend, metaclass=abc.ABCMeta):
    """Template for backends which manage their own kind of users.

    This is basically every backend with exception of 'core' and 'session'.
    """
    #: Specification how user management works. To be filled by child classes.
    user_management = {
        "data_table" : None, # str
        "data_fields" : None, # [str], does not contain PERSONA_DATA_FIELDS
        "validator" : None, # str
    }

    def __init__(self, configpath):
        super().__init__(configpath)
        self.core = AuthShim(CoreBackend(configpath))

    @classmethod
    @abc.abstractmethod
    def extract_roles(cls, personadata):
        return super().extract_roles(personadata)

    @classmethod
    @abc.abstractmethod
    def db_role(cls, role):
        return super().db_role(role)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

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
        :rtype: {int : {str : object}}
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
        return {d['id'] : d for d in data}

    def set_user_data(self, rs, data, pkeys=None, ukeys=None):
        """Update some keys of a data set. If ``pkeys`` or ``ukeys`` is not
        passed all keys available in ``data`` are updated.

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
                query = \
                  "UPDATE {} SET ({}) = ({}) WHERE persona_id = %s".format(
                      self.user_management['data_table'], ", ".join(ukeys),
                      ", ".join(("%s",) * len(ukeys)))
                params = tuple(data[key] for key in ukeys) + (data['id'],)
                ret = self.query_exec(rs, query, params)
                if not ret:
                    raise RuntimeError("Modification failed.")
        return ret

    # @access("user")
    def change_user(self, rs, data):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of users changed
        """
        data = affirm(self.user_management['validator'], data)
        return self.set_user_data(rs, data)

    # @access("user")
    # @singularize("get_data_single")
    def get_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        ids = affirm_array("int", ids)
        return self.retrieve_user_data(rs, ids)
