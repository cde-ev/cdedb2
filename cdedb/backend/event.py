#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

from cdedb.backend.common import AbstractBackend, access_decorator_generator, \
     internal_access_decorator_generator, make_RPCDaemon, \
     run_RPCDaemon, AuthShim
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import glue, PERSONA_DATA_FIELDS_MOD, PERSONA_DATA_FIELDS, \
     EVENT_USER_DATA_FIELDS, extract_realm
from cdedb.config import Config
from cdedb.backend.core import CoreBackend
from cdedb.database.connection import Atomizer
import argparse

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))

class EventBackend(AbstractBackend):
    """Take note of the fact that some personas are orgas and thus have
    additional actions available."""
    realm = "event"

    def __init__(self, configpath):
        super().__init__(configpath)
        self.core = AuthShim(CoreBackend(configpath))

    @classmethod
    def extract_roles(cls, personadata):
        return super().extract_roles(personadata)

    @classmethod
    def db_role(cls, role):
        return super().db_role(role)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    def retrieve_user_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        query = glue(
            "SELECT {} FROM event.user_data AS u JOIN core.personas AS p",
            "ON u.persona_id = p.id WHERE p.id = ANY(%s)").format(
                ", ".join(PERSONA_DATA_FIELDS + EVENT_USER_DATA_FIELDS))

        ret = self.query_all(rs, query, (ids,))
        if len(ret) != len(ids):
            self.logger.warn(
                "Wrong number of data sets found ({} instead of {}).".format(
                    len(ret), len(ids)))
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
                                  ukeys=EVENT_USER_DATA_FIELDS)

    def set_user_data(self, rs, data, pkeys=None, ukeys=None):
        """Update only some keys of a data set. If ``pkeys`` or ``ukeys`` is not
        passed all keys available in ``data`` are updated.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :type pkeys: [str]
        :param pkeys: keys pretaining to the persona
        :type ukeys: [str]
        :param ukeys: keys pretaining to the event user
        :rtype: int
        :returns: number of changed entries
        """
        realm = None
        if data['id'] == rs.user.persona_id:
            realm = rs.user.realm
        else:
            query = "SELECT status FROM core.personas WHERE id = %s"
            realm = extract_realm(
                self.query_one(rs, query, (data['id'],))['status'])
        if realm != self.realm:
            raise ValueError("Wrong realm for persona.")

        if not pkeys:
            pkeys = tuple(key for key in data if key in PERSONA_DATA_FIELDS)
        if not ukeys:
            ukeys = tuple(key for key in data if key in EVENT_USER_DATA_FIELDS)

        if rs.user.persona_id != data['id'] and not self.is_admin(rs):
            raise RuntimeError("Not enough privileges.")

        pdata = {key:data[key] for key in pkeys}
        with Atomizer(rs):
            self.core.set_persona_data(rs, pdata)
            query = glue("UPDATE event.user_data SET ({}) = ({})",
                         "WHERE persona_id = %s").format(
                             ", ".join(ukeys), ", ".join(("%s",) * len(ukeys)))
            return self.query_exec(
                rs, query, tuple(data[key] for key in ukeys) + (data['id'],))

    @access("user")
    def change_user(self, rs, data):
        """Change a data set. Note that you need privileges to edit someone
        elses data set.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type data: {str : object}
        :rtype: int
        :returns: number of users changed
        """
        data = affirm("event_user_data", data)
        self.set_user_data(rs, data)

    @access("user")
    def get_data(self, rs, ids):
        """
        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: [{str : object}]
        """
        return self.retrieve_user_data(rs, ids)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for event services.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    event_backend = EventBackend(args.configpath)
    conf = Config(args.configpath)
    event_server = make_RPCDaemon(event_backend, conf.EVENT_SOCKET,
                                  access_log=conf.EVENT_ACCESS_LOG)
    run_RPCDaemon(event_server, conf.EVENT_STATE_FILE)
