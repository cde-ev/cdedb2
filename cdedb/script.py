#!/usr/bin/env python3

"""This module provides some generic scripting functionalities.

This should be used in scripts to make them more uniform and cut down
on boilerplate.

Additionally this provides some level of guidance on how to interact
with the production environment.
"""

import getpass
import os
import pathlib
import tempfile
import time
from types import TracebackType
from typing import Any, Optional, Type

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.config import Config, SecretsConfig
from cdedb.common import ALL_ROLES, PathLike, RequestState, User, make_proxy
from cdedb.database.connection import Atomizer, IrradiatedConnection
from cdedb.frontend.common import setup_translations

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

_CONFIG = Config()
_TRANSLATIONS = setup_translations(_CONFIG)


__all__ = ['DryRunError', 'Script', 'ScriptAtomizer']


class Script:
    backend_map = {
        "core": CoreBackend,
        "cde": CdEBackend,
        "past_event": PastEventBackend,
        "ml": MlBackend,
        "assembly": AssemblyBackend,
        "event": EventBackend,
    }

    def __init__(self, persona_id: int, dbuser: str, dbname: str = 'cdb',
                 check_system_user: bool = True, dry_run: bool = True,
                 cursor: psycopg2.extensions.cursor = psycopg2.extras.RealDictCursor,
                 configpath: Optional[PathLike] = None,
                 **config: Any):
        """Setup a helper class containing everything you might need for a script.

        :param persona_id: Default ID for the user performing the actions.
        :param dbuser: Database user for the connection.
        :param dbname: Database against which to run the script. Defaults to `'cdb'`.
            May be overridden via environment variable during the evolution trial.
        :param check_system_user: Whether or not ot check for the correct invoking user,
            you need to have a really good reason to turn this off.
        :param dry_run: Whether or not to keep any changes after a transaction.
        :param cursor: CursorFactory for the cursor used by this connection.
        :param configpath: Path to additional config file. Mutually exclusive with
            `config`. In production this has a default.
        :param config: Additional config options via keyword arguments. Mutually
            exclusive with `configpath`.
        """

        if check_system_user and getpass.getuser() != "www-data":
            raise RuntimeError("Must be run as user www-data.")

        self.persona_id = persona_id
        self.dry_run = dry_run

        # Setup config and connection.
        self._conn: psycopg2.extensions.connection = None
        self._atomizer: Optional[ScriptAtomizer] = None
        self._tempfile = None
        self.configpath = None
        if pathlib.Path("/PRODUCTIONVM").exists():
            self.configpath = "/etc/cdedb-application-config.py"
        if config and configpath:
            raise ValueError("Mustn't specify both config and configpath.")
        elif config:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                for k, v in config.items():
                    f.write(f"{k} = {v}\n")
                f.flush()
                self._tempfile = f
                self.configpath = pathlib.Path(f.name)
        elif configpath:
            configpath = pathlib.Path(configpath)
            if configpath.is_file():
                self.configpath = configpath
        self.config = Config(self.configpath)
        self._connect(dbuser, dbname, cursor)

    def _connect(self, dbuser: str, dbname: str, cursor: psycopg2.extensions.cursor
                 ) -> None:
        """Create and save a dabase connection."""
        if self._conn:
            return
        secrets = SecretsConfig(self.configpath)

        # Allow overriding the dbname via environment variable for evolution trial.
        dbname = os.environ.get('EVOLUTION_TRIAL_OVERRIDE_DBNAME', dbname)

        connection_parameters = {
            "dbname": dbname,
            "user": dbuser,
            "password": secrets["CDB_DATABASE_ROLES"][dbuser],
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

    def make_backend(self, realm: str, *, proxy: bool = True):  # type: ignore[no-untyped-def]
        """Create backend, either as a proxy or not."""
        backend = self.backend_map[realm](self.configpath)
        return make_proxy(backend) if proxy else backend

    def rs(self, persona_id: int = None) -> RequestState:
        """Create a RequestState."""
        rs = RequestState(
            sessionkey=None,
            apitoken=None,
            user=User(
                persona_id=self.persona_id if persona_id is None else persona_id,
                roles=ALL_ROLES,
            ),
            request=None,  # type: ignore[arg-type]
            notifications=[],
            mapadapter=None,  # type: ignore[arg-type]
            requestargs=None,
            errors=[],
            values=None,
            begin=None,
            lang="de",
            translations=_TRANSLATIONS,
        )
        rs.conn = rs._conn = self._conn
        return rs

    def __del__(self) -> None:
        """When deleting this instance, delete the temporary file if it still exists."""
        if self._tempfile and self.configpath:
            self.configpath.unlink(missing_ok=True)

    def __enter__(self) -> IrradiatedConnection:
        """Thin wrapper around `ScriptAtomizer`."""
        if not self._atomizer:
            self._atomizer = ScriptAtomizer(self.rs(), dry_run=self.dry_run)
        return self._atomizer.__enter__()

    def __exit__(self, exc_type: Optional[Type[Exception]],
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> bool:
        """Thin wrapper around `ScriptAtomizer`."""
        if self._atomizer is None:
            raise RuntimeError("Impossible.")
        return self._atomizer.__exit__(exc_type, exc_val, exc_tb)


class DryRunError(Exception):
    """
    Signify that the script ran successfully, but no changes should be
    committed.
    """


class ScriptAtomizer(Atomizer):
    """Subclassing Atomizer to add some time logging and a dry run mode.

    :param dry_run: If True, do not commit changes if script ran successfully,
        instead roll back.
    """
    start_time: float

    def __init__(self, rs: RequestState, *, dry_run: bool = True) -> None:
        self.dry_run = bool(os.environ.get('EVOLUTION_TRIAL_OVERRIDE_DRY_RUN', dry_run))
        super().__init__(rs)

    def __enter__(self) -> IrradiatedConnection:
        self.start_time = time.monotonic()
        return super().__enter__()

    def __exit__(self, exc_type: Optional[Type[Exception]],  # type: ignore[override]
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> bool:
        """Calculate time taken and provide success message.

        Ensure the transaction is rolled back if self.dry_run is True.

        Suppress traceback for DryRunErrors by returning True.
        """
        time_diff = time.monotonic() - self.start_time

        def formatmsg(msg: str) -> str:
            return f"{msg} Time taken: {time_diff:.3f} seconds."

        if exc_type is None:
            if self.dry_run:
                msg = "Aborting Dry Run!"
                exc_type = DryRunError
                exc_val = DryRunError(formatmsg(msg))
                exc_tb = None
            else:
                msg = "Success!"
        elif exc_type == DryRunError:
            msg = "Aborting Dry Run!"
        else:
            msg = "Error encountered, rolling back!"
        print()
        print("=" * 80)
        print()
        print(formatmsg(msg))
        print()
        super().__exit__(exc_type, exc_val, exc_tb)
        return isinstance(exc_val, DryRunError)
