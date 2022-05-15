"""Set up the database, including users, tables and population with sample data."""
import os
import pathlib
import subprocess

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.cli.util import has_systemd, is_docker, sanity_check
from cdedb.config import Config, SecretsConfig


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


# TODO is the nobody hack really necessary?
def connect(
    config: Config, secrets: SecretsConfig, as_nobody: bool = False
) -> psycopg2.extensions.connection:
    """Create a very basic database connection.

    This allows to connect to the database specified as CDB_DATABASE_NAME in the given
    config. The connecting user is 'cdb'.

    Only exception from this is if the user wants to connect to the 'nobody' database,
    which is used for very low-level setups (like generation of sample data).
    """

    if as_nobody:
        dbname = user = "nobody"
    else:
        dbname = config["CDB_DATABASE_NAME"]
        user = "cdb"

    connection_parameters = {
        "dbname": dbname,
        "user": user,
        "password": secrets["CDB_DATABASE_ROLES"][user],
        "host": config["DB_HOST"],
        "port": 5432,
        "connection_factory": psycopg2.extensions.connection,
        "cursor_factory": psycopg2.extras.RealDictCursor,
    }
    conn = psycopg2.connect(**connection_parameters)
    conn.set_client_encoding("UTF8")
    conn.set_session(autocommit=True)

    return conn


@sanity_check
def create_database_users(conf: Config) -> None:
    """Drop all existent databases and add the database users.

    Acts globally and is idempotent.
    """
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    users_path = repo_path / "cdedb" / "database" / "cdedb-users.sql"

    # TODO remove slapd once we removed opendlap
    stop_services("pgbouncer", "slapd")
    psql("-f", users_path.__fspath__())
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

    # TODO remove slapd once we removed opendlap
    stop_services("pgbouncer", "slapd")
    psql("-f", str(db_path), "-v", f"cdb_database_name={database}")
    restart_services("pgbouncer")

    with connect(conf, secrets) as conn:
        with conn.cursor() as cur:
            cur.execute(tables_path.read_text())
            cur.execute(ldap_path.read_text())


@sanity_check
def populate_database(conf: Config, secrets: SecretsConfig, xss: bool = False) -> None:
    """Populate the database with sample data."""
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    outfile = repo_path / "tests" / "ancillary_files" / "sample_data.sql"
    if not outfile.exists():
        # compile the sample data
        # TODO use a real temporary file instead or do it in memory
        # TODO this is assumed by tests/common.py -- can we resolve this?
        infile = repo_path / "tests" / "ancillary_files" / "sample_data.json"
        compile_sample_data(conf, infile, outfile, xss=xss)

    with connect(conf, secrets) as conn:
        with conn.cursor() as cur:
            cur.execute(outfile.read_text())


def compile_sample_data(conf: Config, infile: pathlib.Path, outfile: pathlib.Path,
                        xss: bool = False) -> None:
    """Consume a .json file and parse the contained sample data to a .sql file.

    The latter can then directly be applied to a database, to populate it with the
    respective sample data.

    The xss-switch decides if the sample data should be contaminated with script
    tags, to check proper escaping afterwards.
    """
    # TODO since the creation of the sample data is a bit invasive, this is done via
    #  a subprocess call. Maybe this can be done a bit more elegant...

    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    script_file = repo_path / "bin" / "create_sample_data_sql.py"

    if xss:
        xss_arg = ["--xss", conf.get("XSS_PAYLOAD") or ""]
    else:
        xss_arg = []

    # give also the repo_path as pythonpath to the subprocess, so it can find the test
    # module
    env = {**os.environ.copy(), "PYTHONPATH": str(repo_path)}
    subprocess.run(
        ["python3", script_file, "--infile", infile, "--outfile", outfile, *xss_arg],
        check=True, env=env,
    )


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
