"""Some utilities for the setup functions."""
import contextlib
import functools
import os
import pathlib
import pwd
from shutil import which
from typing import Any, Callable, Generator


def has_systemd() -> bool:
    return which("systemctl") is not None


def is_docker() -> bool:
    """Does the current process runs on a docker image?"""
    return pathlib.Path("/CONTAINER").is_file()


def is_vm() -> bool:
    """Does the current process runs on a vm image?"""
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
