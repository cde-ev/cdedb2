"""Provide a command line interface for the setup module."""
import pathlib

import click

from cdedb.setup.config import (
    DEFAULT_CONFIGPATH, SecretsConfig, TestConfig, get_configpath as _get_configpath,
)
from cdedb.setup.database import (
    compile_sample_data as _compile_sample_data, create_database as _create_database,
    initiate_databases as _initiate_databases, populate_database as _populate_database,
)
from cdedb.setup.storage import (
    create_log as _create_log, create_storage as _create_storage,
    populate_storage as _populate_storage,
)


def check_configpath() -> None:
    """Helper to check that a configpath is set as environment variable."""
    if not _get_configpath():
        raise RuntimeError("Start by setting a configpath using 'set_configpath'.")


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("configpath")
def set_configpath(configpath: str) -> None:
    """Tells you how to set the given path as configpath."""
    print("Execute the following command in your shell:")
    print(f"export CDEDB_CONFIGPATH={configpath}")


@cli.command()
def default_configpath() -> None:
    """Prints the default configpath.

    This is the default location of the config, which is also used in the vm and docker
    images. Is also used as hardcoded value at some places where its infeasible to get
    the right config path (like the entry point for apache).
    """
    print(DEFAULT_CONFIGPATH)


@cli.command()
def secrets_configpath() -> None:
    """Prints the secrets config path of the current config."""
    check_configpath()
    config = TestConfig()
    print(config["SECRETS_CONFIGPATH"])


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_storage(owner: str) -> None:
    """Create the file storage."""
    check_configpath()
    config = TestConfig()
    _create_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def populate_storage(owner: str) -> None:
    """Populate the file storage with sample data."""
    check_configpath()
    config = TestConfig()
    _populate_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_log(owner: str) -> None:
    """Create the log storage."""
    check_configpath()
    config = TestConfig()
    _create_log(config, owner)


@cli.command()
def initiate_databases() -> None:
    """Creates the database users."""
    config = TestConfig()
    _initiate_databases(config)


@cli.command()
def create_database() -> None:
    """Create the tables of the database from the config."""
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _create_database(config, secrets)


@cli.command()
@click.option("--xss", default=False, help="prepare the database for xss checks")
def populate_database(xss: bool) -> None:
    """Populate the database tables with sample data."""
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _populate_database(config, secrets, xss)


@cli.command()
@click.option("--infile", default="/cdedb2/tests/ancillary_files/sample_data.json",
              help="the json file containing the sample data")
@click.option("--outfile", default="/tmp/sample_data.sql",
              help="the place to store the sql file")
@click.option("--xss", default=False, help="prepare sample data for xss checks")
def compile_sample_data(infile: str, outfile: str, xss: bool) -> None:
    """Parse sample data from a .json to a .sql file."""
    check_configpath()
    config = TestConfig()
    _compile_sample_data(config, pathlib.Path(infile), pathlib.Path(outfile), xss=xss)


@cli.command()
def make_sample_data() -> None:
    """Repopulates the application with sample data."""
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _populate_storage(config)
    _create_database(config, secrets)
    _populate_database(config, secrets)


if __name__ == "__main__":
    cli()
