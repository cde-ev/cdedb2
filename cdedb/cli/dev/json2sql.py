"""Parse a given json dict into sql statements."""
import csv
import pathlib
from collections.abc import Sized
from itertools import chain
from typing import Any, Callable, Optional, TypedDict

from psycopg2.extensions import connection

from cdedb.backend.core import CoreBackend
from cdedb.cli.util import connect
from cdedb.common import CdEDBObject, PsycoJson
from cdedb.config import Config, SecretsConfig
from cdedb.database.conversions import to_db_input
from cdedb.database.query import DatabaseValue_s


class AuxData(TypedDict):
    conn: connection
    core: type[CoreBackend]
    seq_id_tables: list[str]
    cyclic_references: dict[str, tuple[str, ...]]
    constant_replacements: CdEDBObject
    entry_replacements: dict[str, dict[str, Callable[..., Any]]]
    xss_field_excludes: set[str]
    xss_table_excludes: set[str]


def prepare_aux(data: CdEDBObject, config: Config, secrets: SecretsConfig) -> AuxData:
    # Set up a connection to the database
    conn = connect(config, secrets, as_nobody=True)

    core = CoreBackend  # No need to instantiate, we only use statics.

    # Extract some data about the databse tables using the database connection.

    # The following is a list of tables to that do NOT have sequential ids:
    non_seq_id_tables = [
        "cde.org_period",
        "cde.expuls_period",
        "core.postal_code_locations",
    ]

    seq_id_tables = [t for t in data if t not in non_seq_id_tables]
    # Prepare some constants for special casing.

    # This maps full table names to a list of column names in that table that
    # require special care, because they contain cycliy references.
    # They will be removed from the initial INSERT and UPDATEd later.
    cyclic_references: dict[str, tuple[str, ...]] = {
        "event.events": ("lodge_field_id",),
        "event.event_parts": ("camping_mat_field_id",),
        "event.course_tracks": ("course_room_field_id",),
    }

    # This contains a list of replacements performed on the resulting SQL
    # code at the very end. Note that this is the only way to actually insert
    # SQL-syntax. We use it to alway produce a current timestamp, because a
    # fixed timestamp from the start of a test suite won't do.
    constant_replacements = {
        "'---now---'": "now()",
    }

    # For every table we may map one of it's columns to a function which
    # dynamically generates data to insert.
    # The function will get the entire row as a argument.
    entry_replacements = {
        "core.personas":
            {
                "fulltext": core.create_fulltext,
            },
    }

    # For xss checking insert a payload into all string fields except excluded ones.
    xss_field_excludes = {
        "username", "password_hash", "birthday", "telephone", "mobile", "balance",
        "ctime", "atime", "dtime", "foto", "amount", "iban", "granted_at", "revoked_at",
        "issued_at", "processed_at", "tally", "total", "delta", "shortname", "tempus",
        "registration_start", "registration_soft_limit", "registration_hard_limit",
        "part_begin", "part_end", "fee", "field_name",
        "amount_paid", "amount_owed", "payment", "presider_address", "signup_end",
        "vote_begin", "vote_end", "vote_extension_end", "secret", "vote", "salt",
        "hash", "filename", "file_hash", "address", "local_part", "new_balance",
        "modifier_name", "transaction_date", "condition", "donation", "payment_date",
        'etime', 'rtime', 'secret_hash', 'member_total',
    }
    xss_table_excludes = {
        "cde.org_period", "cde.expuls_period",
    }

    return AuxData(
        conn=conn,
        core=core,
        seq_id_tables=seq_id_tables,
        cyclic_references=cyclic_references,
        constant_replacements=constant_replacements,
        entry_replacements=entry_replacements,
        xss_field_excludes=xss_field_excludes,
        xss_table_excludes=xss_table_excludes,
    )


def format_inserts(table_name: str, table_data: Sized, keys: tuple[str, ...],
                   params: list[DatabaseValue_s], aux: AuxData) -> list[str]:
    ret = []
    # Create len(data) many row placeholders for len(keys) many values.
    value_list = ",\n".join((f"({', '.join(('%s',) * len(keys))})",) * len(table_data))
    query = f"INSERT INTO {table_name} ({', '.join(keys)}) VALUES {value_list};"
    params = tuple(to_db_input(p) for p in params)

    # This is a bit hacky, but it gives us access to a psycopg2.cursor
    # object so we can let psycopg2 take care of the heavy lifting
    # regarding correctly inserting the parameters into the SQL query.
    with aux["conn"] as conn:
        with conn.cursor() as cur:
            ret.append(cur.mogrify(query, params).decode("utf8"))
    return ret


def json2sql(config: Config, secrets: SecretsConfig, data: CdEDBObject,
             xss_payload: Optional[str] = None) -> list[str]:
    """Convert a dict loaded from a json file into sql statements.

    The dict contains tables, mapped to columns, mapped to values. The table and column
    names must be the same as in our table definitions. The data may be loaded from
    a json file.

    :param xss_payload: If not None, it will be used as xss payload for the database.
    :returns: A list of sql statements, inserting the given data.
    """
    aux = prepare_aux(data, config, secrets)
    commands: list[str] = []

    # Start off by resetting the sequential ids to 1.
    commands.extend(f"ALTER SEQUENCE IF EXISTS {table}_id_seq RESTART WITH 1;"
                    for table in aux["seq_id_tables"])

    # Prepare insert statements for the tables in the source file.
    for table, table_data in data.items():
        # Skip tables that have no data.
        if not table_data:
            continue

        # The following is similar to `cdedb.AbstractBackend.sql_insert_many
        # But we fill missing keys with None instead of giving an error.
        key_set = set(chain.from_iterable(e.keys() for e in table_data))
        for k in aux["entry_replacements"].get(table, {}).keys():
            key_set.add(k)

        # Remove fields causing cyclic references. These will be handled later.
        key_set -= set(aux["cyclic_references"].get(table, {}))

        # Convert the keys to a tuple to ensure consistent ordering.
        keys = tuple(key_set)
        # FIXME more precise type
        params_list: list[DatabaseValue_s] = []
        for entry in table_data:
            for k in keys:
                if k not in entry:
                    entry[k] = None
                if isinstance(entry[k], dict):
                    entry[k] = PsycoJson(entry[k])
                elif isinstance(entry[k], str) and xss_payload is not None:
                    if (table not in aux["xss_table_excludes"]
                            and k not in aux['xss_field_excludes']):
                        entry[k] = entry[k] + xss_payload
            for k, f in aux["entry_replacements"].get(table, {}).items():
                entry[k] = f(entry)
            params_list.extend(entry[k] for k in keys)

        commands.extend(format_inserts(table, table_data, keys, params_list, aux))

    # Now we update the tables to fix the cyclic references we skipped earlier.
    for table, refs in aux["cyclic_references"].items():
        for entry in data[table]:
            for ref in refs:
                if entry.get(ref):
                    query = f"UPDATE {table} SET {ref} = %s WHERE id = %s;"
                    params = (entry[ref], entry["id"])
                    with aux["conn"] as conn:
                        with conn.cursor() as cur:
                            commands.append(
                                cur.mogrify(query, params).decode("utf8"))

    # Here we set all sequential ids to start with 1001, so that
    # ids are consistent when running the test suite.
    commands.extend(f"SELECT setval('{table}_id_seq', 1000);"
                    for table in aux["seq_id_tables"])

    # Lastly we do some string replacements to cheat in SQL-syntax like `now()`:
    ret = []
    for cmd in commands:
        for k, v in aux["constant_replacements"].items():
            cmd = cmd.replace(k, v)
        ret.append(cmd)

    ret += _insert_postal_code_locations(aux["conn"])

    return ret


def _insert_postal_code_locations(conn: connection) -> list[str]:
    """
    Read geo coordinates of german PLZs and create INSERTs to save them to the database.
    """
    data = pathlib.Path(
        "/cdedb2/tests/ancillary_files/plz.csv").read_text()
    lines = [line for line in data.splitlines() if not line.strip().startswith("#")]
    entries = list(csv.DictReader(lines, delimiter=','))
    command = f"""
        INSERT INTO
            core.postal_code_locations (postal_code, name, earth_location, lat, long)
        VALUES
            {",".join(["(%s, %s, ll_to_earth(%s, %s), %s, %s)"] * len(entries))};
    """
    params = list(chain.from_iterable(
        [
            e['plz'], e['note'].removeprefix(e['plz']).strip(),
            e['lat'], e['lon'], e['lat'], e['lon'],
        ]
        for e in entries
    ))

    with conn:
        with conn.cursor() as cur:
            return [cur.mogrify(command, params).decode("utf8")]
