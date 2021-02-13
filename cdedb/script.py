#!/usr/bin/env python3

"""This module provides some generic scripting functionalities.

This should be used in scripts to make them more uniform and cut down
on boilerplate.

Additionally this provides some level of guidance on how to interact
with the production environment.
"""

import getpass
import gettext
import tempfile
import time
from types import TracebackType
from typing import Any, Optional, Set, Type, cast
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
from cdedb.common import ALL_ROLES, PathLike, RequestState, make_proxy
from cdedb.database.connection import Atomizer, IrradiatedConnection

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)


class User:
    """Mock User (with all roles) to allow backend access."""
    def __init__(self, persona_id: int):
        self.persona_id = persona_id
        self.roles = ALL_ROLES
        self.orga: Set[int] = set()
        self.moderator: Set[int] = set()
        self.presider: Set[int] = set()
        self.username = None
        self.display_name = None
        self.given_names = None
        self.family_name = None


class MockRequestState:
    """Mock RequestState to allow backend usage."""
    def __init__(self, persona_id: int, conn: IrradiatedConnection):
        self.ambience = None
        self.sessionkey = None
        self.user = User(persona_id)
        self.request = None
        self.notifications = None
        self.urls = None
        self.requestargs = None
        self.urlmap = None
        self.values = None
        self.lang = "de"
        self.gettext = gettext.translation('cdedb', languages=["de"],
                                           localedir="/cdedb2/i18n").gettext
        self.ngettext = gettext.translation('cdedb', languages=["de"],
                                            localedir="/cdedb2/i18n").ngettext
        self._coders = None
        self.begin = None
        self.conn = conn
        self._conn = conn
        self.is_quiet = False
        self._errors = None
        self.validation_appraised = True
        self.csrf_alert = False


class _RSFactory(Protocol):
    def __call__(self, persona_id: int = -1) -> RequestState: ...


def setup(persona_id: int, dbuser: str, dbpassword: str,
          check_system_user: bool = True, dbname: str = 'cdb'
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
            "cursor_factory": psycopg2.extras.RealDictCursor
    }
    try:
        cdb = psycopg2.connect(**connection_parameters, host="localhost")
    except psycopg2.OperationalError as e:  # DB inside Docker listens on "cdb"
        if "Passwort-Authentifizierung" in e.args[0]:
            raise  # fail fast if wrong password is the problem
        cdb = psycopg2.connect(**connection_parameters, host="cdb")
    cdb.set_client_encoding("UTF8")

    def rs(persona_id: int = persona_id) -> RequestState:
        return cast(RequestState, MockRequestState(persona_id, cdb))

    return rs


# No return type annotation on purpose, because it confuses IDE autocompletion.
def make_backend(realm: str, proxy: bool = True, *,  # type: ignore
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
            filename = f.name
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
    pass


class Script(Atomizer):
    """Subclassing Atomizer to add some time logging and a dry run mode.

    :param dry_run: If True, do not commit changes if script ran successfully,
        instead roll back.
    """
    def __init__(self, rs: RequestState, *, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        super().__init__(rs)

    def __enter__(self) -> IrradiatedConnection:
        self.start_time = time.time()
        return super().__enter__()

    def __exit__(self, exc_type: Optional[Type[Exception]],  # type: ignore
                 exc_val: Optional[Exception],
                 exc_tb: Optional[TracebackType]) -> bool:
        """Calculate time taken and provide success message.

        Ensure the transaction is rolled back if self.dry_run is True.

        Suppress traceback for DryRunErrors by returning True.
        """
        self.end_time = time.time()
        time_diff = self.end_time - self.start_time
        formatmsg = lambda msg: f"{msg} Time taken: {time_diff:.3f} seconds."
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
