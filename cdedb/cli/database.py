"""Set up the database, including users, tables and population with sample data."""
import json
import pathlib
import subprocess

from cdedb.cli.dev.json2sql import json2sql
from cdedb.cli.util import (
    SAMPLE_DATA_JSON, connect, has_systemd, is_docker, sanity_check,
)
from cdedb.config import Config, SecretsConfig, TestConfig


def restart_services(*services: str) -> None:
    """Restart the given services."""
    if not has_systemd():
        return
    # TODO on the vm, we need 'sudo' to execute systemctl. Can we get rid of this?
    #  The basic problem is that this is needed f.e. in the test suite...
    subprocess.run(["sudo", "systemctl", "restart", *services], check=True)


def stop_services(*services: str) -> None:
    """Stop the given services."""
    if not has_systemd():
        return
    # TODO see above
    subprocess.run(["sudo", "systemctl", "stop", *services], check=True)


def psql(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Execute a command using the psql client.

    This should be used only in cases where a direct connection to the database
    via psycopg2 is not possible, f.e. to create the database.
    """
    if is_docker():
        return subprocess.run(
            ["psql", "postgresql://postgres:passwd@cdb", *args], check=True)
    else:
        # TODO can we use the user kwarg instead of doing the sudo dance?
        # mypy does not know that run passes unknown arguments to Popen
        # return subprocess.run(["psql", *commands], check=True, user="postgres")
        return subprocess.run(["sudo", "-u", "postgres", "psql", *args], check=True)


@sanity_check
def create_database_users(conf: Config) -> None:
    """Drop all existent databases and add the database users.

    Acts globally and is idempotent.
    """
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    users_path = repo_path / "cdedb" / "database" / "cdedb-users.sql"

    stop_services("pgbouncer", "slapd")
    psql("-f", users_path.__fspath__())
    # we do not restart slapd, since it needs a proper database structure to start
    restart_services("pgbouncer")


@sanity_check
def create_database(conf: Config, secrets: SecretsConfig) -> None:
    """Create the database and add the table definitions.

    Does not yet populate it with actual data.
    """
    database = conf["CDB_DATABASE_NAME"]
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    db_path = repo_path / "cdedb" / "database" / "cdedb-db.sql"
    tables_path = repo_path / "cdedb" / "database" / "cdedb-tables.sql"
    ldap_path = repo_path / "cdedb" / "database" / "cdedb-ldap.sql"

    stop_services("pgbouncer", "slapd")
    psql("-f", str(db_path), "-v", f"cdb_database_name={database}")
    # we do not restart slapd, since it needs a proper populated database
    restart_services("pgbouncer")

    with connect(conf, secrets) as conn:
        with conn.cursor() as cur:
            cur.execute(tables_path.read_text())
            cur.execute(ldap_path.read_text())


@sanity_check
def populate_database(conf: TestConfig, secrets: SecretsConfig,
                      xss: bool = False) -> None:
    """Populate the database with sample data."""
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    infile = repo_path / SAMPLE_DATA_JSON
    with open(infile) as f:
        data = json.load(f)
    xss_payload = conf.get("XSS_PAYLOAD", "") if xss else ""
    sql_commands = "\n".join(json2sql(conf, secrets, data, xss_payload=xss_payload))

    with connect(conf, secrets) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_commands)

    if not xss:
        restart_services("slapd")


def remove_prepared_transactions(conf: Config, secrets: SecretsConfig) -> None:
    """Clean up stale prepared transactions.

    Having these around messes up the whole system and is really painful as they
    are pretty much invisible to the rest of the application.
    """
    with connect(conf, secrets) as conn:
        transactions = conn.tpc_recover()
        for xid in transactions:
            print(f"Removing {xid}")
            conn.tpc_rollback(xid)
