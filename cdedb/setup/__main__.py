import pathlib

import click

from cdedb.setup.config import (
    BasicConfig, SecretsConfig, TestConfig, get_configpath as _get_configpath,
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
    if not _get_configpath():
        raise RuntimeError("Start by setting a configpath using 'set_configpath'.")


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("configpath")
def set_configpath(configpath: str) -> None:
    print("Execute the following command in your shell:")
    print(f"export CDEDB_CONFIGPATH={configpath}")


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_storage(owner: str) -> None:
    check_configpath()
    config = TestConfig()
    _create_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def populate_storage(owner: str) -> None:
    check_configpath()
    config = TestConfig()
    _populate_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_log(owner: str) -> None:
    check_configpath()
    config = TestConfig()
    _create_log(config, owner)


@cli.command()
def initiate_databases() -> None:
    config = BasicConfig()
    _initiate_databases(config)


@cli.command()
def create_database() -> None:
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _create_database(config, secrets)


@cli.command()
@click.option("--xss", default=False, help="prepare the database for xss checks")
def populate_database(xss: bool) -> None:
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
    check_configpath()
    config = TestConfig()
    _compile_sample_data(config, pathlib.Path(infile), pathlib.Path(outfile), xss=xss)


if __name__ == "__main__":
    cli()
