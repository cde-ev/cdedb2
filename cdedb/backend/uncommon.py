#!/usr/bin/env python3

"""More common infrastructure for the backend services.

This provides :py:class:`AbstractUserBackend` and should technically be
a part of :py:mod:`cdedb.backend.common`, but then we get fatal circular
dependencies.
"""

from cdedb.database.connection import Atomizer
from cdedb.common import glue, extract_realm, PERSONA_DATA_FIELDS, \
    PERSONA_DATA_FIELDS_MOD
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

    def affirm_realm(self, rs, ids):
        """Check that all personas corresponding to the ids are in the realm
        of this class.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        """
        realm = None
        if (ids,) == (rs.user.persona_id,):
            realm = rs.user.realm
        else:
            query = "SELECT status FROM core.personas WHERE id = ANY(%s)"
            data = self.query_all(rs, query, (ids,))
            if len(data) != len(ids):
                raise ValueError("Invalid ids.")
            for d in data:
                realm = realm or extract_realm(d['status'])
                if realm != extract_realm(d['status']):
                    raise ValueError("Differing realms.")
        if realm != self.realm:
            raise ValueError("Wrong realm for persona.")

    def retrieve_user_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        query = glue(
            "SELECT {} FROM {} AS u JOIN core.personas AS p",
            "ON u.persona_id = p.id WHERE p.id = ANY(%s)").format(
                ", ".join(PERSONA_DATA_FIELDS +
                          self.user_management['data_fields']),
                self.user_management['data_table'])
        ret = self.query_all(rs, query, (ids,))
        if len(ret) != len(ids):
            raise ValueError("Invalid ids requested.")
        return ret

    def set_complete_user_data(self, rs, data):
        """This requires that all possible keys are present. Often you may
        want to use :py:meth:`set_user_data` instead.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of changed entries
        """
        return self.set_user_data(rs, data, pkeys=PERSONA_DATA_FIELDS_MOD,
                                  ukeys=self.user_management['data_fields'])

    def set_user_data(self, rs, data, pkeys=None, ukeys=None):
        """Update only some keys of a data set. If ``pkeys`` or ``ukeys`` is not
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
        with Atomizer(rs):
            self.core.set_persona_data(rs, pdata)
            query = "UPDATE {} SET ({}) = ({}) WHERE persona_id = %s".format(
                self.user_management['data_table'], ", ".join(ukeys),
                ", ".join(("%s",) * len(ukeys)))
            return self.query_exec(
                rs, query, tuple(data[key] for key in ukeys) + (data['id'],))

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
        self.set_user_data(rs, data)

    # @access("user")
    def get_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        ids = affirm_array("int", ids)
        return self.retrieve_user_data(rs, ids)
