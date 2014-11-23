#!/usr/bin/env python3

"""The event backend provides means to organize events and provides a user
variant for external participants.
"""

from cdedb.backend.uncommon import AbstractUserBackend
from cdedb.backend.common import (
    access, internal_access, make_RPCDaemon, run_RPCDaemon,
    affirm_validation as affirm, affirm_array_validation as affirm_array,
    singularize)
from cdedb.common import glue, EVENT_USER_DATA_FIELDS
from cdedb.config import Config
from cdedb.database.connection import Atomizer
import argparse

class EventBackend(AbstractUserBackend):
    """Take note of the fact that some personas are orgas and thus have
    additional actions available."""
    realm = "event"
    user_management = {
        "data_table" : "event.user_data",
        "data_fields" : EVENT_USER_DATA_FIELDS,
        "validator" : "event_user_data",
    }

    def establish(self, sessionkey, method, allow_internal=False):
        ret = super().establish(sessionkey, method,
                                allow_internal=allow_internal)
        if ret.user.is_persona:
            ret.user.orga = self.orga_infos(ret, (ret.user.persona_id,))
        return ret

    @classmethod
    def is_admin(cls, rs):
        return super().is_admin(rs)

    @access("persona")
    @singularize("orga_info")
    def orga_infos(self, rs, ids):
        """List events organized by personas.

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

    @access("event_user")
    @singularize("participation_info")
    def participation_infos(self, rs, ids):
        """List events visited.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type ids: [int]
        :rtype: {int : [dict]}
        :returns: Keys are the ids and items are the event lists.
        """
        ids = affirm_array("int", ids)
        query = glue(
            "SELECT p.persona_id, p.event_id, e.title AS event_name,",
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

    @access("event_user")
    def change_user(self, rs, data):
        return super().change_user(rs, data)

    @access("event_user")
    @singularize("get_data_single")
    def get_data(self, rs, ids):
        return super().get_data(rs, ids)

    @access("persona")
    def list_events(self, rs):
        """List all events.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :rtype: {int: str}
        :returns: Mapping of event ids to titles.
        """
        query = "SELECT id, title FROM event.events"
        data = self.query_all(rs, query, tuple())
        return {e['id'] : e['title'] for e in data}

    @access("persona")
    def list_courses(self, rs, event_id):
        """List all courses of an event.

        :type rs: :py:class:`cdedb.backend.common.BackendRequestState`
        :type event_id: int
        :rtype: {int: str}
        :returns: Mapping of course ids to titles.
        """
        event_id = affirm("int", event_id)
        query = "SELECT id, title FROM event.courses WHERE event_id = %s"
        data = self.query_all(rs, query, (event_id,))
        return {e['id'] : e['title'] for e in data}

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
