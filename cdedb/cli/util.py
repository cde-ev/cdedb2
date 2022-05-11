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


def command_group_from_folder(group_folder: pathlib.Path):
    """Collect click commands from files of a given directory.

    The files must contain exactly one function decorated with the click.command()
    decorator and named like the file (e.g. test_evolution.py containing the function
    test_evolution()). It may contain arbitrary additional functions.

    Take attention that each file is executed during reading, so be aware that they do
    not apply any unwanted side effects!

    The command may make full use of clicks argument and option decorators to change
    its behaviour.
    """

    class FolderCommands(click.MultiCommand):
        def list_commands(self, context):
            return sorted(
                f.name[:-3].replace("_", "-") for f in group_folder.iterdir() if f.name.endswith(".py"))

        def get_command(self, context, command_name):
            namespace = {}
            name = command_name.replace("-", "_")
            command_file = group_folder / f"{name}.py"
            with open(command_file) as f:
                code = compile(f.read(), command_file, 'exec')
                eval(code, namespace, namespace)
            return namespace[name]

    return FolderCommands
