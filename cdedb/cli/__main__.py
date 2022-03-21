"""Provide a command line interface for the setup module.

Most of these are just wrappers around methods in their resepective submodule
and should not be called directly.
"""
import getpass
import os
import pathlib

import click

from cdedb.cli.database import (
    compile_sample_data, connect, create_database, create_database_users,
    populate_database,
)
from cdedb.cli.server import serve
from cdedb.cli.storage import create_log, create_storage, populate_storage
from cdedb.cli.util import switch_user
from cdedb.config import DEFAULT_CONFIGPATH, SecretsConfig, TestConfig, set_configpath

pass_config = click.make_pass_decorator(TestConfig, ensure=True)
pass_secrets = click.make_pass_decorator(SecretsConfig, ensure=True)

@click.group()
@click.option("--configpath", envvar="CDEDB_CONFIGPATH", default=DEFAULT_CONFIGPATH,
              type=pathlib.Path, show_default=True)
def cli(configpath: pathlib.Path) -> None:
    """Command line interface for setup of CdEDB.

    This is divided in command subgroups for the different points of setup.

    To change the setup process, you can provide a custom path to your configuration
    file. This may also be done by setting the CDEDB_CONFIGPATH environment variable.
    """
    set_configpath(configpath)

@cli.command("serve")
def serve_cmd() -> None:
    serve()

@cli.group(name="config")
def config() -> None:
    """Interact with the config file."""
    pass


@config.command(name="get")
@click.argument("variable")
@pass_config
def get_config_var(config: TestConfig, variable: str) -> None:
    """Retrieve the given variable from the current config."""
    click.echo(config[variable])


@config.command(name="default-configpath")
def get_default_configpath() -> None:
    """Get the default configpath."""
    click.echo(DEFAULT_CONFIGPATH)


@cli.group(name="filesystem")
@click.option("--owner",
    help="Use this user as the owner.",
    default=lambda: getpass.getuser(),
    show_default="current user")
@click.pass_context
def filesystem(ctx: click.Context, owner: str) -> None:
    """Preparations regarding the file system."""
    ctx.obj = owner


@filesystem.group(name="storage")
def storage() -> None:
    """Storage"""
    pass


@storage.command(name="create")
@click.pass_obj
@pass_config
def create_storage_cmd(config: TestConfig, owner: str) -> None:
    """Create the file storage."""
    with switch_user(owner):
        create_storage(config)


@storage.command(name="populate")
@click.pass_obj
@pass_config
def populate_storage_cmd(config: TestConfig, owner: str) -> None:
    """Populate the file storage with sample data."""
    with switch_user(owner):
        populate_storage(config)


@filesystem.group(name="log")
def log() -> None:
    """Log stuff."""
    pass


@log.command(name="create")
@click.pass_obj
@pass_config
def create_log_cmd(config: TestConfig, owner: str) -> None:
    """Create the log storage."""
    with switch_user(owner):
        create_log(config)


@cli.group(name="db")
def database() -> None:
    """Preparations regarding the database."""
    pass


@database.command("create-users")
@pass_config
def create_database_users_cmd(config: TestConfig) -> None:
    """Creates the database users."""
    create_database_users(config)


@database.command(name="create")
@pass_secrets
@pass_config
def create_database_cmd(config: TestConfig, secrets: SecretsConfig) -> None:
    """Create the tables of the database from the config."""
    create_database(config, secrets)


@database.command(name="populate")
@click.option("--xss/--no-xss", default=False, help="prepare the database for xss checks")
@pass_secrets
@pass_config
def populate_database_cmd(
    config: TestConfig, secrets: SecretsConfig, xss: bool
) -> None:
    """Populate the database tables with sample data."""
    populate_database(config, secrets, xss)


@cli.group(name="dev")
def development() -> None:
    """High-level helpers for development."""
    pass


# TODO in which category should we do this?
@development.command(name="compile-sample-data")
@click.option("--infile", default="/cdedb2/tests/ancillary_files/sample_data.json",
              help="the json file containing the sample data")
@click.option("--outfile", default="/tmp/sample_data.sql",
              help="the place to store the sql file")
@click.option("--xss/--no-xss", default=False, help="prepare sample data for xss checks")
@pass_config
def compile_sample_data_cmd(config: TestConfig, infile: str, outfile: str, xss: bool) -> None:
    """Parse sample data from a .json to a .sql file."""
    compile_sample_data(config, pathlib.Path(infile), pathlib.Path(outfile), xss=xss)


@development.command(name="make-sample-data")
@click.option("--owner",
    help="Use this user as the owner of storage and logs.",
    default=lambda: getpass.getuser(),
    show_default="current user")
@pass_secrets
@pass_config
def make_sample_data(config: TestConfig, secrets: SecretsConfig, owner: str) -> None:
    """Repopulates the application with sample data."""
    with switch_user(owner):
        create_log(config)
        create_storage(config)
        populate_storage(config)
    create_database_users(config)
    create_database(config, secrets)
    populate_database(config, secrets)


@development.command(name="execute-sql-script")
@click.option("--file", "-f", type=pathlib.Path, help="the script to execute")
@click.option('-v', '--verbose', count=True)
def execute_sql_script(file: pathlib.Path, verbose: int) -> None:
    config = TestConfig()
    secrets = SecretsConfig()
    with connect(config, secrets) as conn:
        with conn.cursor() as curr:
            curr.execute(file.read_text())
            if verbose > 0:
                if verbose > 1:
                    click.echo(curr.query)
                    click.echo(curr.statusmessage)
                if curr.rowcount != -1:
                    for x in curr:
                        click.echo(x)


def main() -> None:
    try:
        # Set euid/egid to the user invoking sudo if executed with sudo
        with switch_user(os.environ.get("SUDO_USER", getpass.getuser())):
            cli()
    except PermissionError as e:
        raise PermissionError("Unable to perform this command due to missing permissions."
            " Some commands allow invoking them as root and passing a --owner.") from e

if __name__ == "__main__":
    main()
