"""Parse the sample data from a json data file into sql statements."""

import json
import pathlib
import sys
from itertools import chain
from typing import Any, Callable, Dict, List, Set, Sized, Tuple, Type, TypedDict

from psycopg2.extensions import connection

from cdedb.backend.common import DatabaseValue_s
from cdedb.backend.core import CoreBackend
from cdedb.common import CdEDBObject, PsycoJson
from cdedb.config import TestConfig
from cdedb.script import Script


class AuxData(TypedDict):
    conn: connection
    core: Type[CoreBackend]
    seq_id_tables: List[str]
    cyclic_references: Dict[str, Tuple[str, ...]]
    constant_replacements: CdEDBObject
    entry_replacements: Dict[str, Dict[str, Callable[..., Any]]]
    xss_field_excludes: Set[str]
    xss_table_excludes: Set[str]


def prepare_aux(data: CdEDBObject) -> AuxData:
    # Note that we do not care about the actual backend but only the db connection.
    conn = Script(dbuser="nobody", dbname="nobody", check_system_user=False).rs().conn

    core = CoreBackend  # No need to instantiate, we only use statics.

    # Extract some data about the databse tables using the database connection.

    # The following is a list of tables to that do NOT have sequential ids:
    non_seq_id_tables = [
        "cde.org_period",
        "cde.expuls_period",
    ]

    seq_id_tables = [t for t in data if t not in non_seq_id_tables]
    # Prepare some constants for special casing.

    # This maps full table names to a list of column names in that table that
    # require special care, because they contain cycliy references.
    # They will be removed from the initial INSERT and UPDATEd later.
    cyclic_references: Dict[str, Tuple[str, ...]] = {
        "event.events": ("lodge_field", "course_room_field", "camping_mat_field"),
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
        "nonmember_surcharge", "part_begin", "part_end", "fee", "field_name",
        "amount_paid", "amount_owed", "payment", "presider_address", "signup_end",
        "vote_begin", "vote_end", "vote_extension_end", "secret", "vote", "salt",
        "hash", "filename", "file_hash", "address", "local_part", "new_balance",
        "modifier_name",
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


def format_inserts(table_name: str, table_data: Sized, keys: Tuple[str, ...],
                   params: List[DatabaseValue_s], aux: AuxData) -> List[str]:
    ret = []
    # Create len(data) many row placeholders for len(keys) many values.
    value_list = ",\n".join((f"({', '.join(('%s',) * len(keys))})",) * len(table_data))
    query = f"INSERT INTO {table_name} ({', '.join(keys)}) VALUES {value_list};"
    # noinspection PyProtectedMember
    params = tuple(aux["core"]._sanitize_db_input(p) for p in params)  # pylint: disable=protected-access

    # This is a bit hacky, but it gives us access to a psycopg2.cursor
    # object so we can let psycopg2 take care of the heavy lifting
    # regarding correctly inserting the parameters into the SQL query.
    with aux["conn"] as conn:
        with conn.cursor() as cur:
            ret.append(cur.mogrify(query, params).decode("utf8"))
    return ret


def build_commands(data: CdEDBObject, aux: AuxData, xss: str) -> List[str]:
    commands: List[str] = []

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
        params_list: List[DatabaseValue_s] = []
        for entry in table_data:
            for k in keys:
                if k not in entry:
                    entry[k] = None
                if isinstance(entry[k], dict):
                    entry[k] = PsycoJson(entry[k])
                elif isinstance(entry[k], str) and xss:
                    if (table not in aux["xss_table_excludes"]
                            and k not in aux['xss_field_excludes']):
                        entry[k] = entry[k] + xss
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

    return ret


def compile_sample_data_sql(config: TestConfig, infile: pathlib.Path,
                            outfile: pathlib.Path, xss: bool) -> None:
    """Parse the sample data from a json data file into sql statements."""
    with open(infile) as f:
        data = json.load(f)

    assert isinstance(data, dict)
    aux = prepare_aux(data)
    xss_payload = config.get("XSS_PAYLOAD", "") if xss else ""
    commands = build_commands(data, aux, xss_payload)

    with open(outfile, "w") if outfile != "-" else sys.stdout as f:
        for cmd in commands:
            print(cmd, file=f)
