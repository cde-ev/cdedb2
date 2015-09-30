#!/usr/bin/env python3

"""This is a very specialised backend component for doing session lookup,
basically providing the data for instantiating
:py:class:`cdedb.frontend.common.FrontendRequestState`. It does have
it's own realm, which does not occur anywhere else. We have to make do
without most of the infrastructure, since we are providing it;
additionally we mock out some of it (like e.g. the @access
decorator). Everything is a bit special in here.
"""

from cdedb.database.connection import connection_pool_factory
from cdedb.backend.common import make_RPCDaemon, run_RPCDaemon
from cdedb.common import glue, make_root_logger, now
from cdedb.config import Config, SecretsConfig
import cdedb.validation as validate
import psycopg2.extensions
import argparse
import logging

def access(fun):
    """Decorator mock to set ``access_list`` attribute, so ``fun`` will be
    registered for RPC."""
    fun.access_list = True
    return fun

class SessionBackend:
    """This is not derived from
    :py:class:`cdedb.backend.common.AbstractBackend` since the general
    base class makes more assumptions than we can fulfill.
    """
    realm = "session"

    def __init__(self, configpath):
        """
        :type configpath: str
        """
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        make_root_logger("cdedb.backend",
                         getattr(self.conf, "SESSION_BACKEND_LOG"),
                         self.conf.LOG_LEVEL,
                         syslog_level=self.conf.SYSLOG_LEVEL,
                         console_log_level=self.conf.CONSOLE_LOG_LEVEL)
        ## To prevent lots of serialization failures due to races for
        ## updating time stamps if a user opens several connections at once
        ## we lower the isolation level for this backend.
        ##
        ## This may cause artifacts, but those are not worrisome since the
        ## writes made are: setting is_active to False (never to True) and
        ## updating atime (which does not suffer too much from a lost write,
        ## since the competing write will be pretty similar).
        self.connpool = connection_pool_factory(
            self.conf.CDB_DATABASE_NAME, ("cdb_anonymous", "cdb_persona"),
            secrets,
            isolation_level=psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED)
        ## logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.session")
        self.validate_sessionkey = lambda k: k == secrets.SESSION_LOOKUP_KEY

    def establish(self, sessionkey, method, allow_internal=False):
        """Mock of :py:meth:`cdedb.backend.common.AbstractBackend.establish`.

        :type sessionkey: str
        :type method: str
        :type allow_internal: bool
        :param allow_internal: ignored, exists for signature compatability
        """
        if self.validate_sessionkey(sessionkey) and method == "lookupsession":
            return True
        else:
            self.logger.warning("Invalid session lookup key {}.".format(
                sessionkey))
            return None

    @access
    def lookupsession(self, _, sessionkey, ip):
        """Resolve a session key (originally stored in a cookie) into the data
        required for a
        :py:class:`cdedb.frontend.common.FrontendRequestState`. We bind
        sessions to IPs, so they get automatically invalidated if the IP
        changes.

        The ignored first parameter is the request state in all other
        rpc methods and kept for consintency.

        :type sessionkey: str
        :type ip: str
        :rtype: {str: object}
        """
        persona_id = None
        data = None
        if (validate.is_printable_ascii(sessionkey)
                and validate.is_printable_ascii(ip) and sessionkey):
            query = glue("SELECT persona_id, ip, is_active, atime, ctime",
                         "FROM core.sessions WHERE sessionkey = %s")
            with self.connpool["cdb_anonymous"] as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (sessionkey,))
                    if cur.rowcount == 1:
                        data = cur.fetchone()
                    else:
                        self.logger.info("Got invalid session key '{}'.".format(
                            sessionkey))
        if data:
            deactivate = False
            if data["is_active"]:
                if data["ip"] == ip:
                    timestamp = now()
                    if (data["atime"] + self.conf.SESSION_TIMEOUT >= timestamp):
                        if (data["ctime"] + self.conf.SESSION_LIFESPAN
                                >= timestamp):
                            ## here we finally verified the session key
                            persona_id = data["persona_id"]
                        else:
                            deactivate = True
                            self.logger.info("TTL exceeded for {}".format(
                                sessionkey))
                    else:
                        deactivate = True
                        self.logger.info("Session timed out: {}".format(
                            sessionkey))
                else:
                    deactivate = True
                    self.logger.info("IP mismatch ({} vs {}) for {}".format(
                        ip, data["ip"], sessionkey))
            else:
                self.logger.info("Got inactive session key '{}'.".format(
                    sessionkey))
            if deactivate:
                query = glue("UPDATE core.sessions SET is_active = False",
                             "WHERE sessionkey = %s")
                with self.connpool["cdb_anonymous"] as conn:
                    with conn.cursor() as cur:
                        cur.execute(query, (sessionkey,))
        ret = {'persona_id': persona_id,
               'db_privileges': None,
               'status': None,
               'display_name': "",
               'given_names': "",
               'family_name': "",
               'username': "",}
        if persona_id:
            query = glue("UPDATE core.sessions SET atime = now()",
                         "WHERE sessionkey = %s")
            query2 = glue(
                "SELECT status, db_privileges, display_name, given_names,",
                "family_name, is_active, username FROM core.personas",
                "WHERE id = %s")
            with self.connpool["cdb_persona"] as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (sessionkey,))
                    cur.execute(query2, (persona_id,))
                    data = cur.fetchone()
            if data["is_active"]:
                ret.update(data)
            else:
                self.logger.warning("Found inactive user {}".format(persona_id))
        return ret

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run CdEDB Backend for session lookup.')
    parser.add_argument('-c', default=None, metavar='/path/to/config',
                        dest="configpath")
    args = parser.parse_args()
    session_backend = SessionBackend(args.configpath)
    conf = Config(args.configpath)
    session_server = make_RPCDaemon(session_backend, conf.SESSION_SOCKET,
                                    access_log=conf.SESSION_ACCESS_LOG)
    run_RPCDaemon(session_server, conf.SESSION_STATE_FILE)
