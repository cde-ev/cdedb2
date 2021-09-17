#!/usr/bin/env python3

"""This module provides some generic scripting functionalities.

This should be used in scripts to make them more uniform and cut down
on boilerplate.

Additionally this provides some level of guidance on how to interact
with the production environment.
"""

import getpass
import tempfile
import time
from types import TracebackType
from typing import Any, Optional, Type
from typing_extensions import Protocol

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.config import Config
from cdedb.common import ALL_ROLES, PathLike, RequestState, User, make_proxy
from cdedb.database.connection import Atomizer, IrradiatedConnection
from cdedb.frontend.common import setup_translations

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

_CONFIG = Config()
_TRANSLATIONS = setup_translations(_CONFIG)


def mock_user(persona_id: int) -> User:
    return User(
        persona_id=persona_id,
        roles=ALL_ROLES,
    )


class _RSFactory(Protocol):
    # pylint: disable=pointless-statement
    def __call__(self, persona_id: int = -1) -> RequestState: ...


def setup(persona_id: int, dbuser: str, dbpassword: str,
          check_system_user: bool = True, dbname: str = 'cdb',
          cursor: psycopg2.extensions.cursor = psycopg2.extras.RealDictCursor,
          ) -> _RSFactory:
    """This sets up the database.

    :param persona_id: default ID for the owner of the generated request state
    :param dbuser: data base user for connection
    :param dbpassword: password for database user
    :param check_system_user: toggle check for correct invoking user,
        you need to provide a really good reason to turn this off.
    :returns: a factory, that optionally takes a persona ID and gives
        you a facsimile request state object that can be used to call
        into the backends.
    """
    if check_system_user and getpass.getuser() != "www-data":
        raise RuntimeError("Must be run as user www-data.")

    connection_parameters = {
            "dbname": dbname,
            "user": dbuser,
            "password": dbpassword,
            "port": 5432,
            "connection_factory": IrradiatedConnection,
            "cursor_factory": cursor,
    }
    try:
        cdb = psycopg2.connect(**connection_parameters, host="localhost")
    except psycopg2.OperationalError as e:  # DB inside Docker listens on "cdb"
        if "Passwort-Authentifizierung" in e.args[0]:
            raise  # fail fast if wrong password is the problem
        cdb = psycopg2.connect(**connection_parameters, host="cdb")
    cdb.set_client_encoding("UTF8")

    def rs(persona_id: int = persona_id) -> RequestState:
        rs = RequestState(
            sessionkey=None,
            apitoken=None,
            user=mock_user(persona_id),
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
        rs.conn = rs._conn = cdb
        return rs

    return rs


# No return type annotation on purpose, because it confuses IDE autocompletion.
def make_backend(realm: str, proxy: bool = True, *,  # type: ignore[no-untyped-def]
                 configpath: PathLike = None, **config: Any):
    """Instantiate backend objects and wrap them in proxy shims.

    :param realm: selects backend to return
    :param proxy: If True, wrap the backend in a proxy, otherwise return
        the raw backend, which gives access to the low-level SQL methods.
    """
    if realm not in backend_map:
        raise ValueError("Unrecognized realm")
    if config and configpath:
        raise ValueError("Mustn't specify both config and configpath.")
    elif config:
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
            for k, v in config.items():
                f.write(f"{k} = {v}\n")
            f.flush()
            backend = backend_map[realm](f.name)
    else:
        backend = backend_map[realm](configpath)
    if proxy:
        return make_proxy(backend)
    else:
        return backend


backend_map = {
    "core": CoreBackend,
    "cde": CdEBackend,
    "past_event": PastEventBackend,
    "ml": MlBackend,
    "assembly": AssemblyBackend,
    "event": EventBackend,
}


class DryRunError(Exception):
    """
    Signify that the script ran successfully, but no changes should be
    committed.
    """


class Script(Atomizer):
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
