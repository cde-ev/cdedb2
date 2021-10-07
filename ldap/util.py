#!/usr/bin/env python3

"""This file provides some boilerplate to create, update and remove the CdEDB-LDAP.

The "Script" part is a slimmed version of cdedb.script.py. To keep the dependencies
(mostly for docker) very low, we use this instead of the original one. This also adds
some small tricks to handle the docker setting appropriately, since the docker ldap
runs in another container than the cdedb.
"""

import getpass
import os
import pathlib
import tempfile
from types import TracebackType
from typing import Any, IO, Optional, Type, Union

from passlib.hash import sha512_crypt
import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import IrradiatedConnection

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)


def encrypt_password(password: str) -> str:
    """We currently use passlib for password protection."""
    return sha512_crypt.hash(password)

###########
# Scripts #
###########

PathLike = Union[pathlib.Path, str]
_CONFIG = Config()

class TempConfig:
    """Provide a thin wrapper around a temporary file.

    The advantage ot this is that it works with both a given configpath or
    config keyword arguments."""
    def __init__(self, configpath: PathLike = None, **config: Any):
        if config and configpath:
            raise ValueError("Mustn't specify both config and configpath.")
        self._configpath = configpath
        self._config = config
        self._f: Optional[IO[str]] = None

    def __enter__(self) -> Optional[PathLike]:
        if self._config:
            self._f = tempfile.NamedTemporaryFile("w", suffix=".py")
            f = self._f.__enter__()
            for k, v in self._config.items():
                f.write(f"{k} = {v}")
            f.flush()
            return f.name
        return self._configpath

    def __exit__(self, exc_type: Optional[Type[Exception]],
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> Optional[bool]:
        if self._f:
            return self._f.__exit__(exc_type, exc_val, exc_tb)
        return False


class Script:
    def __init__(self, *, dry_run: bool = None,
                 dbuser: str = 'cdb_anonymous', dbname: str = 'cdb',
                 cursor: psycopg2.extensions.cursor = psycopg2.extras.RealDictCursor,
                 configpath: Optional[PathLike] = None, **config: Any):
        """Setup a helper class containing everything you might need for a script.

        The parameters `persona_id`, `dry_run` and `configpath` may be left out, in
        which case they will be read from the environment or set to a reasonable
        default.

        The database name and the `dry_run` parameter may be overridden specifically by
        the `evolution_trial` script.

        :param dry_run: Whether or not to keep any changes after a transaction.
        :param dbuser: Database user for the connection. Defaults to `'cdb_anonymous'`
        :param dbname: Database against which to run the script. Defaults to `'cdb'`.
            May be overridden via environment variable during the evolution trial.
        :param cursor: CursorFactory for the cursor used by this connection.
        :param configpath: Path to additional config file. Mutually exclusive with
            `config`.
        :param config: Additional config options via keyword arguments. Mutually
            exclusive with `configpath`.
        """
        if getpass.getuser() != "root":
            raise RuntimeError("Must be run as user root.")

        # Read configurable data from environment and/or input.
        configpath = configpath or os.environ.get("SCRIPT_CONFIGPATH")
        if dry_run is None:
            dry_run = bool(os.environ.get("SCRIPT_DRY_RUN", True))
        self.dry_run = bool(os.environ.get("EVOLUTION_TRIAL_OVERRIDE_DRY_RUN", dry_run))
        dbname = os.environ.get("EVOLUTION_TRIAL_OVERRIDE_DBNAME", dbname)

        # Setup internals.
        self._conn: psycopg2.extensions.connection = None
        self._tempconfig = TempConfig(configpath, **config)
        with self._tempconfig as p:
            self.config = Config(p)
            self._secrets = SecretsConfig(p)
        self._connect(dbuser, dbname, cursor)

    def _connect(self, dbuser: str, dbname: str, cursor: psycopg2.extensions.cursor
                 ) -> None:
        """Create and save a database connection."""
        if self._conn:
            return

        connection_parameters = {
            "dbname": dbname,
            "user": dbuser,
            "password": self._secrets["CDB_DATABASE_ROLES"][dbuser],
            "port": 5432,
            "connection_factory": IrradiatedConnection,
            "cursor_factory": cursor,
        }
        try:
            self._conn = psycopg2.connect(**connection_parameters, host="localhost")
        except psycopg2.OperationalError as e:  # DB inside Docker listens on "cdb"
            if "Passwort-Authentifizierung" in e.args[0]:
                raise  # fail fast if wrong password is the problem
            if "Password-Authentication" in e.args[0]:
                raise
            self._conn = psycopg2.connect(**connection_parameters, host="cdb")
        self._conn.set_client_encoding("UTF8")
