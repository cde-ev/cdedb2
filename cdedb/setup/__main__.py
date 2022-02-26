import click

from cdedb.setup.config import (
    BasicConfig, SecretsConfig, TestConfig, get_configpath as _get_configpath,
)
from cdedb.setup.database import (
    create_database as _create_database, initiate_databases as _initiate_databases,
    populate_database as _populate_database,
)
from cdedb.setup.storage import (
    create_log as _create_log, create_storage as _create_storage,
    populate_storage as _populate_storage,
)


def check_configpath() -> None:
    if not _get_configpath():
        raise RuntimeError("Start by setting a configpath using 'set_configpath'.")


@click.group()
def cli():
    pass


@cli.command()
@click.argument("configpath")
def set_configpath(configpath):
    print("Execute the following command in your shell:")
    print(f"export CDEDB_CONFIGPATH={configpath}")


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_storage(owner):
    check_configpath()
    config = TestConfig()
    _create_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def populate_storage(owner):
    check_configpath()
    config = TestConfig()
    _populate_storage(config, owner)


@cli.command()
@click.option("--owner", default="www-data", help="owner of the file storage")
def create_log(owner):
    check_configpath()
    config = TestConfig()
    _create_log(config, owner)


@cli.command()
def initiate_databases():
    config = BasicConfig()
    _initiate_databases(config)


@cli.command()
def create_database():
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _create_database(config, secrets)


@cli.command()
@click.option("--xss", default=False, help="prepare the database for xss checks")
def populate_database(xss):
    check_configpath()
    config = TestConfig()
    secrets = SecretsConfig()
    _populate_database(config, secrets, xss)


if __name__ == "__main__":
    cli()
