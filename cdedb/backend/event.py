#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import access_decorator_generator, \
    internal_access_decorator_generator, make_RPCDaemon, run_RPCDaemon, \
    affirm_validation as affirm, affirm_array_validation as affirm_array
from cdedb.common import glue, EVENT_USER_DATA_FIELDS
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import argparse

access = access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))
internal_access = internal_access_decorator_generator(
    ("anonymous", "persona", "user", "member", "event_admin", "admin"))

class EventBackend(AbstractUserBackend):
    """Take note of the fact that some personas are orgas and thus have
    additional actions available."""
    realm = "event"
    user_management = {
        "data_table" : "event.user_data",
        "data_fields" : EVENT_USER_DATA_FIELDS,
        "validator" : "event_user_data",
    }

    @classmethod
    def extract_roles(cls, personadata):
        return super().extract_roles(personadata)

    @classmethod
    def db_role(cls, role):
        return super().db_role(role)

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    def orga_info(self, rs, ids):
        """List events organized by persona.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int: {int}}
        """
        ids = affirm_array("int", ids)
        query = glue("SELECT persona_id, event_id FROM event.orgas",
                     "WHERE persona_id = ANY(%s)")
        data = self.query_all(rs, query, (ids,))
        ret = {}
        for anid in ids:
            ret[anid] = {x['event_id'] for x in data if x['persona_id'] == anid}
        return ret

    @access("user")
    def participation_info(self, rs, ids):
        """List events visited.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : [dict]}
        :returns: Keys are the ids and items are the event lists.
        """
        ids = affirm_array("int", ids)
        query = glue(
            "SELECT p.persona_id, p.event_id, e.longname AS event_name,",
            "p.course_id, c.title AS course_name, p.is_instructor, p.is_orga",
            "FROM event.participants AS p",
            "INNER JOIN event.events AS e ON (p.event_id = e.id)",
            "LEFT OUTER JOIN event.courses AS c ON (p.course_id = c.id)",
            "WHERE p.persona_id = ANY(%s) ORDER BY p.event_id")
        event_data = self.query_all(rs, query, (ids,))
        ret = {}
        for anid in ids:
            ret[anid] = tuple(x for x in event_data if x['persona_id'] == anid)
        return ret

    @access("user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("user")
    def get_data(self, rs, ids):
        return super().get_data(rs, ids)

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
