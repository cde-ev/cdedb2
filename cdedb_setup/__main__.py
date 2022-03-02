"""Provide a command line interface for the setup module."""
import contextlib
import os
import pathlib
import pwd
from typing import Generator, Optional

import click
from cdedb_setup.config import (
    DEFAULT_CONFIGPATH, SecretsConfig, TestConfig, set_configpath as _set_configpath,
)
from cdedb_setup.database import (
    compile_sample_data as _compile_sample_data, create_database as _create_database,
    create_database_users as _create_database_users,
    populate_database as _populate_database,
)
from cdedb_setup.storage import (
    create_log as _create_log, create_storage as _create_storage,
    populate_storage as _populate_storage,
)


@contextlib.contextmanager
def switch_user(user: str) -> Generator[None, None, None]:
    """Use as context manager to temporary switch the running user's effective uid."""
    real_user = pwd.getpwuid(os.getuid())
    if real_user.pw_name != "root":
        raise PermissionError("May only run as root.")
    wanted_user = pwd.getpwnam(user)
    os.seteuid(wanted_user.pw_uid)
    # os.setegid(wanted_user.pw_gid)
    yield
    os.seteuid(real_user.pw_uid)
    # os.setegid(real_user.pw_gid)


@click.group()
@click.option("--configpath", envvar="CDEDB_CONFIGPATH", default=DEFAULT_CONFIGPATH,
              type=pathlib.Path, show_default=True, help="Or set via CDEDB_CONFIGPATH environment variable.")
def cli(configpath: pathlib.Path) -> None:
    """Command line interface for setup of CdEDB."""
    _set_configpath(configpath)


@cli.group()
def config() -> None:
    """Interact with the config file."""
    pass


@config.command()
@click.argument("variable")
def get(variable: str) -> None:
    """Retrieve the given variable from the current config."""
    config = TestConfig()
    print(config[variable])


@cli.group()
def filesystem() -> None:
    """Preparations regarding the file system."""
    pass


@filesystem.command()
@click.option("--user", help="Use this user as the owner.")
def create_storage(user: str) -> None:
    """Create the file storage."""
    config = TestConfig()
    if user:
        with switch_user(user):
            _create_storage(config)
    else:
        _create_storage(config)


@filesystem.command()
@click.option("--user", help="Use this user as the owner.")
def populate_storage(user: str) -> None:
    """Populate the file storage with sample data."""
    config = TestConfig()
    if user:
        with switch_user(user):
            _populate_storage(config)
    else:
        _populate_storage(config)


@filesystem.command()
@click.option("--user", help="Use this user as the owner.")
def create_log(user: str) -> None:
    """Create the log storage."""
    config = TestConfig()
    if user:
        with switch_user(user):
            _create_log(config)
    else:
        _create_log(config)


@cli.group()
def database() -> None:
    """Preparations regarding the database."""
    pass


@database.command()
def create_database_users() -> None:
    """Creates the database users."""
    config = TestConfig()
    _create_database_users(config)


@database.command()
def create_database() -> None:
    """Create the tables of the database from the config."""
    config = TestConfig()
    secrets = SecretsConfig()
    _create_database(config, secrets)


@database.command()
@click.option("--xss", default=False, help="prepare the database for xss checks")
def populate_database(xss: bool) -> None:
    """Populate the database tables with sample data."""
    config = TestConfig()
    secrets = SecretsConfig()
    _populate_database(config, secrets, xss)


@cli.group()
def development() -> None:
    """High-level helpers for development."""
    pass


@cli.command()
@click.option("--infile", default="/cdedb2/tests/ancillary_files/sample_data.json",
              help="the json file containing the sample data")
@click.option("--outfile", default="/tmp/sample_data.sql",
              help="the place to store the sql file")
@click.option("--xss", default=False, help="prepare sample data for xss checks")
def compile_sample_data(infile: str, outfile: str, xss: bool) -> None:
    """Parse sample data from a .json to a .sql file."""
    config = TestConfig()
    _compile_sample_data(config, pathlib.Path(infile), pathlib.Path(outfile), xss=xss)


@development.command()
@click.option("--user", help="Use this as the owner of the storage and log.")
@click.pass_context
def make_sample_data(context: click.Context, user: Optional[str]) -> None:
    """Repopulates the application with sample data."""
    context.invoke(create_storage, user=user)
    context.invoke(populate_storage, user=user)
    context.invoke(create_database)
    context.invoke(populate_database)


if __name__ == "__main__":
    cli()
