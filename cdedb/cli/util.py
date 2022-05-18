"""Some utilities for the setup functions."""
import contextlib
import functools
import getpass
import os
import pathlib
import pwd
from shutil import which
from typing import Any, Callable, Generator

import click
import psycopg2.extensions
import psycopg2.extras

from cdedb.common import RequestState, User
from cdedb.common.roles import ALL_ROLES
from cdedb.config import Config, SecretsConfig, TestConfig

pass_config = click.make_pass_decorator(TestConfig, ensure=True)
pass_secrets = click.make_pass_decorator(SecretsConfig, ensure=True)


def has_systemd() -> bool:
    return which("systemctl") is not None


def is_docker() -> bool:
    """Does the current process run on a docker image?"""
    return pathlib.Path("/CONTAINER").is_file()


def is_vm() -> bool:
    """Does the current process run on a vm image?"""
    return not is_docker()


def sanity_check(fun: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for invasive actions which are forbidden on protected instances."""

    @functools.wraps(fun)
    def new_fun(*args: Any, **kwargs: Any) -> Any:
        if pathlib.Path("/PRODUCTIONVM").is_file():
            raise RuntimeError("Refusing to touch live instance!")
        if pathlib.Path("/OFFLINEVM").is_file():
            raise RuntimeError("Refusing to touch orga instance!")
        return fun(*args, **kwargs)

    return new_fun


@contextlib.contextmanager
def switch_user(user: str) -> Generator[None, None, None]:
    """Use as context manager to temporary switch the running user's effective uid."""
    original_uid = os.geteuid()
    original_gid = os.getegid()
    wanted_user = pwd.getpwnam(user)
    try:
        os.setegid(wanted_user.pw_gid)
        os.seteuid(wanted_user.pw_uid)
        yield
    except PermissionError as e:
        raise PermissionError(
            f"Insufficient permissions to switch to user {user}."
        ) from e
    finally:
        os.setegid(original_gid)
        os.seteuid(original_uid)


def get_user() -> str:
    """Get the user running the process.

    This resolves 'sudo' calls to the correct user invoking the process via sudo.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user or sudo_user == "root":
        return getpass.getuser()
    return sudo_user


# TODO is the nobody hack really necessary?
def connect(
    config: Config, secrets: SecretsConfig, as_nobody: bool = False
) -> psycopg2.extensions.connection:
    """Create a very basic database connection.

    This allows to connect to the database specified as CDB_DATABASE_NAME in the given
    config. The connecting user is 'cdb'.

    Only exception from this is if the user wants to connect to the 'nobody' database,
    which is used for very low-level setups (like generation of sample data).
    """

    if as_nobody:
        dbname = user = "nobody"
    else:
        dbname = config["CDB_DATABASE_NAME"]
        user = "cdb"

    connection_parameters = {
        "dbname": dbname,
        "user": user,
        "password": secrets["CDB_DATABASE_ROLES"][user],
        "host": config["DB_HOST"],
        "port": 5432,
        "connection_factory": psycopg2.extensions.connection,
        "cursor_factory": psycopg2.extras.RealDictCursor,
    }
    conn = psycopg2.connect(**connection_parameters)
    conn.set_client_encoding("UTF8")
    conn.set_session(autocommit=True)

    return conn


def fake_rs(conn: psycopg2.extensions.connection, persona_id: int = 0) -> RequestState:
    """Create a RequestState which may be used during more elaborated commands.

    This is needed when we want to interact with the CdEDB on a higher level of
    abstraction. Note that the capabilities of this RequestState are limited, f.e. only
    backend functions may work properly due to missing translations.
    """
    rs = RequestState(
        sessionkey=None,
        apitoken=None,
        user=User(
            persona_id=persona_id,
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
        # translations=translations, TODO is this really necessary?
        translations=None,  # type: ignore[arg-type]
    )
    rs.conn = rs._conn = conn
    return rs
