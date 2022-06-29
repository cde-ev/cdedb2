#!/usr/bin/env python3

"""This module provides some generic scripting functionalities.

This should be used in scripts to make them more uniform and cut down
on boilerplate.

Additionally this provides some level of guidance on how to interact
with the production environment.
"""
import contextlib
import getpass
import gettext
import os
import pathlib
import tempfile
import time
from pkgutil import resolve_name
from types import TracebackType
from typing import IO, Any, Dict, Mapping, Optional, Tuple, Type

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.cli.util import fake_rs, redirect_to_file
from cdedb.common import AbstractBackend, PathLike, RequestState, make_proxy
from cdedb.common.n_ import n_
from cdedb.config import Config, SecretsConfig, get_configpath, set_configpath
from cdedb.database.connection import Atomizer, IrradiatedConnection
from cdedb.frontend.common import setup_translations

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

__all__ = ['DryRunError', 'Script', 'ScriptAtomizer']


class TempConfig:
    """Provide a thin wrapper around a temporary file.

    The advantage of this is that it works with both a given configpath xor config
    keyword arguments. If either of both is given, the current config path is used.
    If this is not set, we use the DEFAULT_CONFIGPATH.

    If config keyword arguments are given, the config options from the real configpath
    (taken from the environment) are used as fallback values.
    If a configpath is given, only the config options specified there are taken into
    account.
    """

    def __init__(self, configpath: PathLike = None, **config: Any):
        if configpath and config:
            raise ValueError(f"Do not provide both config ({config}) and"
                             f" configpath ({configpath}).")
        self._configpath = configpath
        self._config = config
        # this will be used to hold the current configpath from the environment
        # and restore it later on
        self._real_configpath: pathlib.Path
        self._f: Optional[IO[str]] = None

    def __enter__(self) -> None:
        # This also sets the config path to the default one if no config path is set.
        self._real_configpath = get_configpath(fallback=True)
        if self._config:
            secrets = SecretsConfig()
            self._f = tempfile.NamedTemporaryFile("w", suffix=".py")
            f = self._f.__enter__()
            # copy the real_config into the temporary config
            with open(self._real_configpath, "r") as cf:
                real_config = cf.read()
            f.write(real_config)
            # now, add all keyword config options. Since they are added _after_ the
            # real_config options, they overwrite them if necessary
            for k, v in self._config.items():
                if k in secrets:
                    msg = ("Override secret config options via kwarg is not possible."
                           " Please use the SECRET_CONFIGPATH config argument instead.")
                    raise ValueError(msg)
                f.write(f"\n{k} = {v}")
            f.flush()
            set_configpath(f.name)
        elif self._configpath:
            assert self._configpath is not None
            set_configpath(self._configpath)

    def __exit__(self, exc_type: Optional[Type[Exception]],
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> Optional[bool]:
        # restore the real configpath
        set_configpath(self._real_configpath)
        if self._f:
            return self._f.__exit__(exc_type, exc_val, exc_tb)
        return False

    def __str__(self) -> str:
        if self._config:
            return str(self._config)
        elif self._configpath:
            return pathlib.Path(self._configpath).read_text()
        else:
            return ""


class Script:
    backend_map = {
        "core": "CoreBackend",
        "cde": "CdEBackend",
        "past_event": "PastEventBackend",
        "ml": "MlBackend",
        "assembly": "AssemblyBackend",
        "event": "EventBackend",
    }

    def __init__(self, *, persona_id: int = None, dry_run: bool = None,
                 dbuser: str = 'cdb_anonymous', dbname: str = 'cdb',
                 outfile: PathLike = None, outfile_append: bool = None,
                 cursor: psycopg2.extensions.cursor = psycopg2.extras.RealDictCursor,
                 check_system_user: bool = True, configpath: Optional[PathLike] = None,
                 **config: Any):
        """Setup a helper class containing everything you might need for a script.

        The parameters `persona_id`, `dry_run` and `configpath` may be left out, in
        which case they will be read from the environment or set to a reasonable
        default.

        The database name and the `dry_run` parameter may be overridden specifically by
        the `evolution_trial` script.

        :param persona_id: Default ID for the user performing the actions.
        :param dry_run: Whether or not to keep any changes after a transaction.
        :param dbuser: Database user for the connection. Defaults to `'cdb_anonymous'`
        :param dbname: Database against which to run the script. Defaults to `'cdb'`.
            May be overridden via environment variable during the evolution trial.
        :param outfile: If given, redirect stdout and stderr into this file.
        :param outfile_append: If True, append to the outfile, rather than replace.
        :param cursor: CursorFactory for the cursor used by this connection.
        :param check_system_user: Whether or not ot check for the correct invoking user,
            you need to have a really good reason to turn this off.
        :param configpath: Path to additional config file. Mutually exclusive with
            `config`.
        :param config: Additional config options via keyword arguments. Mutually
            exclusive with `configpath`.
        """
        if check_system_user and getpass.getuser() != "www-data":
            raise RuntimeError("Must be run as user www-data.")

        # Read configurable data from environment and/or input.
        # Priority is "parameter > environment variable".
        configpath = configpath or os.environ.get("SCRIPT_CONFIGPATH")
        outfile = outfile or os.environ.get("SCRIPT_OUTFILE")
        self.outfile = pathlib.Path(outfile) if outfile else None
        self.outfile_append = (bool(os.environ.get("SCRIPT_OUTFILE_APPEND"))
                               if outfile_append is None else outfile_append)

        # Allow overriding for evolution trial.
        # Priority is "override > parameter > environment variable".
        if persona_id is None:
            persona_id = int(os.environ.get("SCRIPT_PERSONA_ID", -1))
        self.persona_id = int(
            os.environ.get("EVOLUTION_TRIAL_OVERRIDE_PERSONA_ID", persona_id))
        if dry_run is None:
            dry_run = bool(os.environ.get("SCRIPT_DRY_RUN", True))
        self.dry_run = bool(os.environ.get("EVOLUTION_TRIAL_OVERRIDE_DRY_RUN", dry_run))
        dbname = os.environ.get("EVOLUTION_TRIAL_OVERRIDE_DBNAME", dbname)

        # Setup internals.
        self._redirect: Optional[contextlib.AbstractContextManager[None]] = None
        self._atomizer: Optional[ScriptAtomizer] = None
        self._conn: psycopg2.extensions.connection = None
        self._tempconfig = TempConfig(configpath, **config)
        with self._tempconfig:
            self.config = Config()
            self._secrets = SecretsConfig()
        self._translations: Optional[Mapping[str, gettext.NullTranslations]]
        self._backends: Dict[Tuple[str, bool], AbstractBackend]
        self._translations = None
        self._backends = {}
        self._request_states: Dict[int, RequestState] = {}
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
            "host": self.config["DB_HOST"],
            "port": self.config["DIRECT_DB_PORT"],
            "connection_factory": IrradiatedConnection,
            "cursor_factory": cursor,
        }
        self._conn = psycopg2.connect(**connection_parameters)
        self._conn.set_client_encoding("UTF8")

    def make_backend(self, realm: str, *, proxy: bool = True):  # type: ignore[no-untyped-def]
        """Create backend, either as a proxy or not."""
        if ret := self._backends.get((realm, proxy)):
            return ret
        with self._tempconfig:
            backend_name = self.backend_map[realm]
            backend = resolve_name(f"cdedb.backend.{realm}.{backend_name}")()
        self._backends.update({
            (realm, True): make_proxy(backend),
            (realm, False): backend,
        })
        return self._backends[(realm, proxy)]

    def rs(self, persona_id: int = None) -> RequestState:
        """Create a RequestState."""
        persona_id = self.persona_id if persona_id is None else persona_id
        if ret := self._request_states.get(persona_id):
            return ret
        if self._translations is None:
            self._translations = setup_translations(self.config)
        rs = fake_rs(self._conn, persona_id)
        self._request_states[persona_id] = rs
        return rs

    def __enter__(self) -> IrradiatedConnection:
        """Thin wrapper around `ScriptAtomizer`."""
        if not self._atomizer:
            self._atomizer = ScriptAtomizer(self.rs(), dry_run=self.dry_run)
        if self.outfile:
            self._redirect = redirect_to_file(self.outfile, self.outfile_append)
            self._redirect.__enter__()
        return self._atomizer.__enter__()

    def __exit__(self, exc_type: Optional[Type[Exception]],
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> bool:
        """Thin wrapper around `ScriptAtomizer`."""
        if self._atomizer is None:
            raise RuntimeError(n_("Impossible."))
        if self._redirect:
            self._redirect.__exit__(exc_type, exc_val, exc_tb)
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
        self.dry_run = dry_run
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
