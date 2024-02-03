"""Provide a command line interface for the setup module.

Most of these are just wrappers around methods in their resepective submodule
and should not be called directly.
"""
import difflib
import json
import pathlib
import sys
from typing import Any

import click

from cdedb.cli.database import (
    create_database, create_database_users, populate_database,
    remove_prepared_transactions,
)
from cdedb.cli.dev.json2sql import json2sql
from cdedb.cli.dev.serve import serve_debugger
from cdedb.cli.dev.sql2json import sql2json
from cdedb.cli.storage import (
    create_log, create_storage, populate_event_keeper, populate_sample_event_keepers,
    populate_storage, reset_config,
)
from cdedb.cli.util import (
    execute_sql_script, get_user, pass_config, pass_secrets, redirect_to_file,
    switch_user,
)
from cdedb.common import CustomJSONEncoder
from cdedb.config import DEFAULT_CONFIGPATH, SecretsConfig, TestConfig, set_configpath


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


@cli.group(name="config")
def config() -> None:
    """Interact with the config file."""


@config.command(name="get")
@click.argument("variable")
@pass_config
def get_config_var(config: TestConfig, variable: str) -> None:
    """Retrieve the given variable from the current config."""
    try:
        val = config[variable]
    except KeyError:
        raise click.UsageError(f"Invalid config key '{variable}'.") from None
    else:
        click.echo(val)


@config.command(name="default-configpath")
def get_default_configpath() -> None:
    """Get the default configpath."""
    click.echo(DEFAULT_CONFIGPATH)


@cli.group(name="filesystem")
@click.option("--owner",
    help="Use this user as the owner.",
    default=get_user,
    show_default="current user")
@click.pass_context
def filesystem(ctx: click.Context, owner: str) -> None:
    """Preparations regarding the file system."""
    ctx.obj = owner


@filesystem.group(name="storage")
def storage() -> None:
    """Storage"""


@storage.command(name="create")
@click.pass_obj
@pass_config
def create_storage_cmd(config: TestConfig, owner: str) -> None:
    """Create the file storage."""
    click.echo(f"Create storage directory at {config['STORAGE_DIR']}.")
    with switch_user(owner):
        create_storage(config)


@storage.command(name="populate")
@click.pass_obj
@pass_config
def populate_storage_cmd(config: TestConfig, owner: str) -> None:
    """Populate the file storage with sample data."""
    click.echo(f"Populate storage directory at {config['STORAGE_DIR']}.")
    with switch_user(owner):
        populate_storage(config)
        populate_sample_event_keepers(config)


@storage.command(name="populate-event-keeper")
@click.argument('event_id', type=int)
@click.pass_obj
@pass_config
def populate_event_keeper_cmd(config: TestConfig, owner: str, event_id: int) -> None:
    """Populate the event keeper."""
    path = config['STORAGE_DIR'] / 'event_keeper'
    click.echo(f"Populate event keeper at {path}.")
    with switch_user(owner):
        path.mkdir(parents=True, exist_ok=True)
        populate_event_keeper(config, [event_id])


@filesystem.group(name="log")
def log() -> None:
    """Log stuff."""


@log.command(name="create")
@click.pass_obj
@pass_config
def create_log_cmd(config: TestConfig, owner: str) -> None:
    """Create the log storage."""
    click.echo(f"Create log directory at {config['LOG_DIR']}.")
    with switch_user(owner):
        create_log(config)


@cli.group(name="db")
def database() -> None:
    """Preparations regarding the database."""


@database.command("create-users")
@pass_config
def create_database_users_cmd(config: TestConfig) -> None:
    """Creates the database users."""
    click.echo("Create database users.")
    create_database_users(config)


@database.command(name="create")
@pass_secrets
@pass_config
def create_database_cmd(config: TestConfig, secrets: SecretsConfig) -> None:
    """Create the tables of the database from the config."""
    click.echo(f"Create database {config['CDB_DATABASE_NAME']}.")
    create_database(config, secrets)
    # to reset all old states of the database, we also remove prepared transactions.
    remove_prepared_transactions(config, secrets)


# TODO move this in development section
@database.command(name="populate")
@click.option(
    "--xss/--no-xss", default=False, help="prepare the database for xss checks")
@pass_secrets
@pass_config
def populate_database_cmd(
    config: TestConfig, secrets: SecretsConfig, xss: bool,
) -> None:
    """Populate the database tables with sample data."""
    click.echo(f"Populate database {config['CDB_DATABASE_NAME']}.")
    populate_database(config, secrets, xss)


@database.command(name="remove-transactions")
@pass_secrets
@pass_config
def remove_transactions_cmd(config: TestConfig, secrets: SecretsConfig) -> None:
    """Clean up stale prepared transactions."""
    remove_prepared_transactions(config, secrets)


#
# Development commands
#

@cli.group(name="dev")
def development() -> None:
    """Helpers for development, expecting a running CdEDBv2."""


@development.command(name="compile-sample-data-json")
@click.option("-o", "--outfile", default="/tmp/sample_data.json",
              type=click.Path(), help="the place to store the sql file")
@click.option("-s", "--silent", default=False, type=bool)
@pass_secrets
@pass_config
def compile_sample_data_json(config: TestConfig, secrets: SecretsConfig,
                             outfile: pathlib.Path, silent: bool) -> None:
    """Generate a JSON-file from the current state of the database."""
    data = sql2json(config, secrets, silent=silent)
    with open(outfile, "w", encoding='UTF-8') as f:
        json.dump(data, f, cls=CustomJSONEncoder, indent=4, ensure_ascii=False)
        f.write("\n")


@development.command(name="compile-sample-data-sql")
@click.option("-i", "--infile",
              default="/cdedb2/tests/ancillary_files/sample_data.json",
              type=click.Path(), help="the json file containing the sample data")
@click.option("-o", "--outfile", default="/tmp/sample_data.sql",
              type=click.Path(), help="the place to store the sql file")
@click.option(
    "--xss/--no-xss", default=False, help="prepare sample data for xss checks")
@pass_secrets
@pass_config
def compile_sample_data_sql(
    config: TestConfig, secrets: SecretsConfig, infile: pathlib.Path,
    outfile: pathlib.Path, xss: bool,
) -> None:
    """Parse sample data from a .json to a .sql file.

    The latter can then directly be applied to a database, to populate it with the
    respective sample data.

    The xss-switch decides if the sample data should be contaminated with script
    tags, to check proper escaping afterwards.
    """
    with open(infile, encoding="utf8") as f:
        data: dict[str, list[Any]] = json.load(f)

    xss_payload = config.get("XSS_PAYLOAD", "") if xss else ""
    commands = json2sql(config, secrets, data, xss_payload=xss_payload)

    with open(outfile, "w") as f:
        for cmd in commands:
            print(cmd, file=f)


@development.command(name="apply-sample-data")
@click.option("--owner",
    help="Use this user as the owner of storage and logs.",
    default=get_user,
    show_default="current user")
@pass_config
def apply_sample_data(config: TestConfig, owner: str) -> None:
    """Repopulates the application with sample data."""
    config, secrets = reset_config(config)
    with switch_user(owner):
        create_log(config)
        create_storage(config)
        populate_storage(config)
        populate_sample_event_keepers(config)
        create_database_users(config)
        create_database(config, secrets)
        populate_database(config, secrets)


@development.command(name="apply-evolution-trial")
@pass_secrets
@pass_config
def apply_evolution_trial(config: TestConfig, secrets: SecretsConfig) -> None:
    create_database_users(config)
    create_database(config, secrets)
    populate_database(config, secrets)


@development.command(name="serve")
@click.option('-t', '--test', is_flag=True)
def serve_debugger_cmd(test: bool) -> None:
    """Serve the cdedb using the werkzeug development server"""
    serve_debugger(test)


@development.command(name="execute-sql-script")
@click.option("--file", "-f", type=pathlib.Path, help="the script to execute")
@click.option('-v', '--verbose', count=True)
@click.option("--as-postgres", is_flag=True)
@click.option("--outfile", "-o", type=pathlib.Path, help="file to write the output to",
              default=None)
@click.option("--outfile-append", is_flag=True)
@pass_secrets
@pass_config
def execute_sql_script_cmd(
        config: TestConfig, secrets: SecretsConfig, file: pathlib.Path, verbose: int,
        as_postgres: bool, outfile: pathlib.Path, outfile_append: bool,
) -> None:
    with redirect_to_file(outfile, outfile_append):
        execute_sql_script(config, secrets, file.read_text(), verbose=verbose,
                           as_postgres=as_postgres)


@development.command(name="describe-database")
@click.option("--outfile", "-o", type=pathlib.Path)
@pass_secrets
@pass_config
def describe_database(config: TestConfig, secrets: SecretsConfig,
                      outfile: pathlib.Path) -> None:
    description_file = pathlib.Path("/cdedb2/bin/describe_database.sql")
    with redirect_to_file(outfile, append=False):
        execute_sql_script(config, secrets, description_file.read_text(), verbose=2)


@development.command(name="check-sample-data-consistency")
@click.pass_context
def check_sample_data_consistency(ctx: click.Context) -> None:
    """Ensure json2sql() -> sql2json() leaves sample_data.json invariant."""
    clean_data = pathlib.Path("/tmp/sample_data.json")
    current_data = pathlib.Path("/cdedb2/tests/ancillary_files/sample_data.json")

    # setup fresh database
    # it does not matter which database we use here, but we don't want to flush the
    # current one, so we use a test database instead.
    set_configpath("/cdedb2/tests/config/test_ldap.py")
    config = TestConfig()
    secrets = SecretsConfig()
    create_database(config, secrets)
    populate_database(config, secrets)

    # get a fresh sample_data.json from this database
    ctx.forward(compile_sample_data_json, outfile=clean_data, silent=True)

    # compare the fresh one with the current one
    with open(clean_data, encoding='UTF-8') as f:
        fresh = f.readlines()
    with open(current_data, encoding='UTF-8') as f:
        current = f.readlines()
    diff = "".join(difflib.unified_diff(
        fresh, current, fromfile="Cleanly generated sampledata.",
        tofile="/cdedb2/tests/ancillary_files/sample_data.json", n=2))
    if diff:
        print(diff, file=sys.stderr)
        sys.exit(1)
    else:
        print("\nConsistent.", file=sys.stdout)


def main() -> None:
    try:
        cli()
    except PermissionError as e:
        raise PermissionError(
            "Unable to perform this command due to missing permissions."
            " Some commands allow invoking them as root and passing a --owner.",
        ) from e


if __name__ == "__main__":
    main()
