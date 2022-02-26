import os
import pathlib
import subprocess
from typing import Union

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from cdedb.setup.config import Config, SecretsConfig
from cdedb.setup.util import is_docker, sanity_check


def start_services(*services: str) -> None:
    """Start the given services."""
    if is_docker():
        return
    for service in services:
        subprocess.run(["sudo", "systemctl", "start", service], check=True)


def stop_services(*services: str) -> None:
    """Stop the given services."""
    if is_docker():
        return
    for service in services:
        subprocess.run(["sudo", "systemctl", "stop", service], check=True)


def psql(*commands: Union[str, pathlib.Path]) -> None:
    """Execute commands using the psql client.

    This should be used only in cases where a direct connection to the database
    via psycopg2 is not possible, f.e. to create the database.
    """
    if is_docker():
        psql = ["psql", "postgresql://postgres:passwd@cdb"]
    else:
        psql = ["sudo", "-u", "postgres", "psql"]
    subprocess.run([*psql, *commands], check=True)


def connect(config: Config, secrets: SecretsConfig, as_nobody: bool = False) -> psycopg2.extensions.connection:
    """Create a very basic database connection.

    In general, only the connection to the database specified in the config as 'cdb'
    user is allowed.

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
def initiate_databases(conf: Config) -> None:
    """Drop all existent databases and add the database users.

    Acts globally and is idempotent.
    """
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    users_path = repo_path / "cdedb" / "database" / "cdedb-users.sql"

    stop_services("pgbouncer", "slapd")
    psql("-f", users_path)
    start_services("pgbouncer")


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
    psql("-f", db_path, "-v", f"cdb_database_name={database}")
    start_services("pgbouncer")

    with connect(conf, secrets) as conn:
        with conn.cursor() as curr:
            curr.execute(tables_path.read_text())
            curr.execute(ldap_path.read_text())


@sanity_check
def populate_database(conf: Config, secrets: SecretsConfig, xss: bool = False) -> None:
    """Populate the database with sample data."""
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    # compile the sample data
    # TODO since the creation of the sample data is a bit invasive, this is done via
    #  a subprocess call. Maybe this can be done a bit more elegant...
    infile = repo_path / "tests" / "ancillary_files" / "sample_data.json"
    # TODO use a real temporary file instead
    outfile = pathlib.Path("/tmp") / "sample_data.sql"
    compile_sample_data(conf, infile, outfile, xss=xss)

    with connect(conf, secrets) as conn:
        with conn.cursor() as curr:
            curr.execute(outfile.read_text())

    # if not xss:
    #     start_services("slapd")


def compile_sample_data(conf: Config, infile: pathlib.Path, outfile: pathlib.Path,
                        xss: bool = False) -> None:
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    script_file = repo_path / "bin" / "create_sample_data_sql.py"

    if xss:
        xss_arg = ["--xss", conf.get("XSS_PAYLOAD") or ""]
    else:
        xss_arg = []

    # give also the repo_path as pythonpath to the subprocess, so it can find the test
    # module
    env = {**os.environ, "PYTHONPATH": repo_path}
    subprocess.run(["python3", script_file,
                    "--infile", infile, "--outfile", outfile, *xss_arg],
                   check=True, env=env)
