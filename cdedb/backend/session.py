#!/usr/bin/env python3

"""This is a very specialised backend component for doing session lookup.

It basically providies the data for instantiating
:py:class:`cdedb.common.RequestState`. It does have it's own realm,
which does not occur anywhere else. We have to make do without most of
the infrastructure, since we are providing it. Everything is a bit
special in here.
"""

import logging
from typing import Optional

import psycopg2.extensions

import cdedb.validationtypes as vtypes
from cdedb.backend.common import verify_validation as verify
from cdedb.common import (
    PERSONA_STATUS_FIELDS, PathLike, User, droid_roles, extract_roles,
    make_root_logger, now,
)
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import connection_pool_factory


class SessionBackend:
    """Single purpose backend to construct a request state.

    This is not derived from
    :py:class:`cdedb.backend.common.AbstractBackend` since the general
    base class makes more assumptions than we can fulfill.
    """
    realm = "session"

    def __init__(self, configpath: PathLike = None):
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)

        # local variable also to prevent closure over secrets
        lookup = {v: k for k, v in secrets['API_TOKENS'].items()}
        self.api_token_lookup = lookup.get

        make_root_logger(
            "cdedb.backend.session", self.conf["SESSION_BACKEND_LOG"],
            self.conf["LOG_LEVEL"], syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        # logger are thread-safe!
        self.logger = logging.getLogger("cdedb.backend.session")
        # To prevent lots of serialization failures due to races for
        # updating time stamps if a user opens several connections at once
        # we lower the isolation level for this backend.
        #
        # This may cause artifacts, but those are not worrisome since the
        # writes made are: setting is_active to False (never to True) and
        # updating atime (which does not suffer too much from a lost write,
        # since the competing write will be pretty similar).
        self.connpool = connection_pool_factory(
            self.conf["CDB_DATABASE_NAME"], ("cdb_anonymous", "cdb_persona"),
            secrets, self.conf["DB_PORT"],
            isolation_level=psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED)

    def lookupsession(self, sessionkey: Optional[str], ip: str) -> User:
        """Raison d'etre.

        Resolve a session key (originally stored in a cookie) into the
        User wrapper required for a :py:class:`cdedb.common.RequestState`. We
        bind sessions to IPs, so they get automatically invalidated if
        the IP changes.
        """
        persona_id = None
        data = None
        sessionkey, sessionkey_errs = verify(vtypes.PrintableASCII, sessionkey)
        ip, ip_errs = verify(vtypes.PrintableASCII, ip)
        if not sessionkey_errs and not ip_errs:
            query = ("SELECT persona_id, ip, is_active, atime, ctime"
                     " FROM core.sessions WHERE sessionkey = %s")
            with self.connpool["cdb_anonymous"] as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (sessionkey,))
                    if cur.rowcount == 1:
                        data = cur.fetchone()
                    else:
                        # log message to be picked up by fail2ban
                        self.logger.warning(
                            f"CdEDB invalid session key from {ip}")
        if data:
            deactivate = False
            if data["is_active"]:
                if data["ip"] == ip:
                    timestamp = now()
                    if (data["atime"] + self.conf["SESSION_TIMEOUT"]
                            >= timestamp):
                        if (data["ctime"] + self.conf["SESSION_LIFESPAN"]
                                >= timestamp):
                            # here we finally verified the session key
                            persona_id = data["persona_id"]
                        else:
                            deactivate = True
                            self.logger.info(f"TTL exceeded for {sessionkey}")
                    else:
                        deactivate = True
                        self.logger.info(f"Session timed out: {sessionkey}")
                else:
                    deactivate = True
                    self.logger.info(
                        f"IP mismatch ({ip} vs {data['ip']}) for {sessionkey}")
            else:
                self.logger.info(f"Got inactive session key {sessionkey}.")
            if deactivate:
                query = ("UPDATE core.sessions SET is_active = False"
                         " WHERE sessionkey = %s")
                with self.connpool["cdb_anonymous"] as conn:
                    with conn.cursor() as cur:
                        cur.execute(query, (sessionkey,))

        if not persona_id:
            return User()

        query = "UPDATE core.sessions SET atime = now() WHERE sessionkey = %s"
        query2 = (f"SELECT id AS persona_id, display_name, given_names,"
                  f" family_name, username, {', '.join(PERSONA_STATUS_FIELDS)}"
                  f" FROM core.personas WHERE id = %s")
        with self.connpool["cdb_persona"] as conn:
            with conn.cursor() as cur:
                cur.execute(query, (sessionkey,))
                cur.execute(query2, (persona_id,))
                data = cur.fetchone()
        if self.conf["LOCKDOWN"] and not (data['is_meta_admin']
                                          or data['is_core_admin']):
            # Short circuit in case of lockdown
            return User()
        if not data["is_active"]:
            self.logger.warning(f"Found inactive user {persona_id}")
            return User()

        vals = {k: data[k] for k in ('persona_id', 'username', 'given_names',
                                     'display_name', 'family_name')}
        return User(roles=extract_roles(data), **vals)

    def lookuptoken(self, apitoken: Optional[str], ip: str) -> User:
        """Raison d'etre deux.

        Resolve an API token (originally submitted via header) into the
        User wrapper required for a :py:class:`cdedb.common.RequestState`.
        """
        ret = User()
        identity = self.api_token_lookup(apitoken)
        if identity:
            ret = User(roles=droid_roles(identity))
            if self.conf['LOCKDOWN'] and 'droid_infra' not in ret.roles:
                ret = User()
        else:
            # log message to be picked up by fail2ban
            self.logger.warning(f"CdEDB invalid API token from {ip}")
        return ret
