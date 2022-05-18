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

from cdedb.config import SecretsConfig, TestConfig

pass_config = click.make_pass_decorator(TestConfig, ensure=True)
pass_secrets = click.make_pass_decorator(SecretsConfig, ensure=True)

# relative path to the sample_data.json file, from the repository root
SAMPLE_DATA_JSON = pathlib.Path("tests") / "ancillary_files" / "sample_data.json"


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


def sanity_check_production(fun: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for invasive actions which are forbidden on production only."""

    @functools.wraps(fun)
    def new_fun(*args: Any, **kwargs: Any) -> Any:
        if pathlib.Path("/PRODUCTIONVM").is_file():
            raise RuntimeError("Refusing to touch live instance!")
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
