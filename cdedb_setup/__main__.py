"""Provide a command line interface for the setup module."""
import contextlib
import os
import pathlib
import pwd
from typing import Generator, Optional

import click
from cdedb_setup.config import (
    DEFAULT_CONFIGPATH, SecretsConfig, TestConfig, set_configpath,
)
from cdedb_setup.database import (
    compile_sample_data, create_database, create_database_users, populate_database,
)
from cdedb_setup.storage import create_log, create_storage, populate_storage


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
    set_configpath(configpath)


@cli.group(name="config")
def _config() -> None:
    """Interact with the config file."""
    pass


@_config.command(name="get")
@click.argument("variable")
def _get_config_var(variable: str) -> None:
    """Retrieve the given variable from the current config."""
    config = TestConfig()
    click.echo(config[variable])


@_config.command(name="default-configpath")
def _get_default_configpath() -> None:
    """Get the default configpath."""
    click.echo(DEFAULT_CONFIGPATH)


@cli.group(name="filesystem")
def _filesystem() -> None:
    """Preparations regarding the file system."""
    pass


@_filesystem.group(name="storage")
def _storage() -> None:
    """Storage"""
    pass


@_storage.command(name="create")
@click.option("--user", help="Use this user as the owner.")
def _create_storage(user: str) -> None:
    """Create the file storage."""
    config = TestConfig()
    if user:
        with switch_user(user):
            create_storage(config)
    else:
        create_storage(config)


@_storage.command(name="populate")
@click.option("--user", help="Use this user as the owner.")
def _populate_storage(user: str) -> None:
    """Populate the file storage with sample data."""
    config = TestConfig()
    if user:
        with switch_user(user):
            populate_storage(config)
    else:
        populate_storage(config)


@_filesystem.group(name="log")
def _log() -> None:
    """Log stuff."""
    pass


@_log.command(name="create")
@click.option("--user", help="Use this user as the owner.")
def _create_log(user: str) -> None:
    """Create the log storage."""
    config = TestConfig()
    if user:
        with switch_user(user):
            create_log(config)
    else:
        create_log(config)


@cli.group(name="database")
def _database() -> None:
    """Preparations regarding the database."""
    pass


@_database.command("create-users")
def _create_database_users() -> None:
    """Creates the database users."""
    config = TestConfig()
    create_database_users(config)


@_database.command(name="create")
def _create_database() -> None:
    """Create the tables of the database from the config."""
    config = TestConfig()
    secrets = SecretsConfig()
    create_database(config, secrets)


@_database.command(name="populate")
@click.option("--xss", default=False, help="prepare the database for xss checks")
def _populate_database(xss: bool) -> None:
    """Populate the database tables with sample data."""
    config = TestConfig()
    secrets = SecretsConfig()
    populate_database(config, secrets, xss)


@cli.group(name="dev")
def _development() -> None:
    """High-level helpers for development."""
    pass


# TODO in which category should we do this?
@cli.command(name="compile-sample-data")
@click.option("--infile", default="/cdedb2/tests/ancillary_files/sample_data.json",
              help="the json file containing the sample data")
@click.option("--outfile", default="/tmp/sample_data.sql",
              help="the place to store the sql file")
@click.option("--xss", default=False, help="prepare sample data for xss checks")
def _compile_sample_data(infile: str, outfile: str, xss: bool) -> None:
    """Parse sample data from a .json to a .sql file."""
    config = TestConfig()
    compile_sample_data(config, pathlib.Path(infile), pathlib.Path(outfile), xss=xss)


@_development.command(name="make-sample-data")
@click.option("--user", help="Use this as the owner of the storage and log.")
@click.pass_context
def _make_sample_data(context: click.Context, user: Optional[str]) -> None:
    """Repopulates the application with sample data."""
    context.invoke(_create_storage, user=user)
    context.invoke(_populate_storage, user=user)
    context.invoke(_create_database)
    context.invoke(_populate_database)


if __name__ == "__main__":
    cli()
