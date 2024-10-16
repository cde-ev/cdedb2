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
from passlib.utils import consteq

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import inspect_validation as inspect, verify_password
from cdedb.common import User, n_, now, setup_logger
from cdedb.common.exceptions import APITokenError
from cdedb.common.fields import PERSONA_STATUS_FIELDS
from cdedb.common.roles import extract_roles
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import connection_pool_factory
from cdedb.models.droid import DynamicAPIToken, StaticAPIToken, resolve_droid_name


class SessionBackend:
    """Single purpose backend to construct a request state.

    This is not derived from
    :py:class:`cdedb.backend.common.AbstractBackend` since the general
    base class makes more assumptions than we can fulfill.
    """
    realm = "session"

    def __init__(self) -> None:
        self.conf = Config()
        secrets = SecretsConfig()

        # local variable also to prevent closure over secrets
        self._validate_static_droid_secret = lambda droid, secret: consteq(
            secrets['API_TOKENS'][droid], secret)

        setup_logger(
            "cdedb.backend.session", self.conf["LOG_DIR"] / "cdedb-backend-session.log",
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
            secrets, self.conf["DB_HOST"], self.conf["DB_PORT"],
            isolation_level=psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED)

    def _is_locked_down(self) -> bool:
        """Helper to determine if CdEDB is locked."""
        if self.conf["LOCKDOWN"]:
            return True
        # we do not have the core backend, so we have to query meta info by hand
        with self.connpool["cdb_anonymous"] as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT info FROM core.meta_info LIMIT 1")
                data = dict(cur.fetchone() or {})
        return data['info'].get("lockdown_web")

    def lookupsession(self, sessionkey: Optional[str], ip: Optional[str]) -> User:
        """Raison d'etre.

        Resolve a session key (originally stored in a cookie) into the
        User wrapper required for a :py:class:`cdedb.common.RequestState`. We
        bind sessions to IPs, so they get automatically invalidated if
        the IP changes.
        """
        persona_id = None
        data = None
        sessionkey, sessionkey_errs = inspect(vtypes.PrintableASCII, sessionkey)
        ip, ip_errs = inspect(vtypes.PrintableASCII, ip)
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
                assert data is not None
        if self._is_locked_down() and not (data['is_meta_admin']
                                           or data['is_core_admin']):
            # Short circuit in case of lockdown
            return User()
        if not data["is_active"]:
            self.logger.warning(f"Found inactive user {persona_id}")
            return User()

        vals = {k: data[k] for k in ('persona_id', 'username', 'given_names',
                                     'display_name', 'family_name')}
        return User(roles=extract_roles(data), **vals)

    def lookuptoken(self, apitoken: Optional[str], ip: Optional[str]) -> User:
        """Raison d'etre deux.

        Resolve an API token (originally submitted via header) into the
        User wrapper required for a :py:class:`cdedb.common.RequestState`.

        A malformed token or a valid token for an unknown droid or
        with an invalid secret will raise an error.
        """
        apitoken, errs = inspect(vtypes.APITokenString, apitoken)
        if not apitoken or errs:
            raise APITokenError(n_("Malformed API token."))

        droid_name, secret = apitoken

        try:
            droid_class, token_id = resolve_droid_name(droid_name)

            if droid_class is None:
                # Droid name did not match any known droid.
                self.logger.warning(
                    f"API token did not match any known droid: {droid_name!r}.")
                raise APITokenError(n_("Unknown droid name."))
            elif issubclass(droid_class, StaticAPIToken):
                if self._validate_static_droid_secret(droid_class.name, secret):
                    ret = droid_class.get_user()
                else:
                    raise APITokenError
            elif issubclass(droid_class, DynamicAPIToken) and token_id:
                ret = self._validate_dynamic_droid_secret(droid_class, token_id, secret)
            else:
                raise APITokenError
        except APITokenError:
            # log message to be picked up by fail2ban.
            self.logger.exception(f"Received invalid API token from {ip}.")
            raise

        # Prevent non-infrastructure droids from access during lockdown.
        if self._is_locked_down() and 'droid_infra' not in ret.roles:
            ret = User()

        return ret

    def _validate_dynamic_droid_secret(self, droid_class: type[DynamicAPIToken],
                                       token_id: int, secret: str) -> User:

        if self.conf['CDEDB_OFFLINE_DEPLOYMENT']:
            raise APITokenError(n_("This API is not available in offline mode."))

        with self.connpool["cdb_anonymous"] as conn:
            with conn.cursor() as cur:
                query = f"""
                    SELECT
                        {','.join(droid_class.database_fields())}, secret_hash
                    FROM {droid_class.database_table}
                    WHERE id = %s
                """
                cur.execute(query, (token_id,))
                data = cur.fetchone()

                # Not a valid token id. Probably garbage input or deleted token.
                if not data:
                    self.logger.warning(
                        f"Access using unknown {droid_class.name}"
                        f" token id: {token_id}.")
                    raise APITokenError(
                        n_("Unknown %(droid_name)s token."),
                        {'droid_name': droid_class.name},
                    )

                data = dict(data)
                secret_hash = data.pop('secret_hash')
                token = droid_class.from_database(data)

                if secret_hash is None or token.rtime:
                    self.logger.warning(
                        f"Access using inactive {droid_class.name} token {token}.")
                    raise APITokenError(
                        n_("This %(droid_name)s token has been revoked."),
                        {'droid_name': droid_class.name},
                    )
                if not verify_password(secret, secret_hash):
                    self.logger.warning(
                        f"Invalid secret for {droid_class.name} token {token}.")
                    raise APITokenError(
                        n_("Invalid %(droid_name)s token."),
                        {'droid_name': droid_class.name},
                    )
                if now() > token.etime:
                    self.logger.warning(
                        f"Access using expired {droid_class.name} token {token}.")
                    raise APITokenError(
                        n_("This %(droid_name)s token has expired."),
                        {'droid_name': droid_class.name},
                    )

                # Log latest access time.
                query = f"""
                    UPDATE {droid_class.database_table}
                    SET atime = now()
                    WHERE id = %s
                """
                cur.execute(query, (token_id,))

        return token.get_user()
