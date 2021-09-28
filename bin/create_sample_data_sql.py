import argparse
import json
from itertools import chain
from typing import Any, Callable, Dict, List, Set, Tuple, Type, TypedDict

from cdedb.backend.common import PsycoJson
from cdedb.backend.core import CoreBackend
from cdedb.common import RequestState, CdEDBObject
from cdedb.script import Script


class AuxData(TypedDict):
    rs: RequestState
    core: Type[CoreBackend]
    PsycoJson: Type[PsycoJson]
    seq_id_tables: List[str]
    cyclic_references: Dict[str, Tuple[str, ...]]
    constant_replacements: CdEDBObject
    entry_replacements: Dict[str, Dict[str, Callable[..., Any]]]
    xss_field_excludes: Set[str]
    xss_table_excludes: Set[str]


def prepare_aux(data: CdEDBObject) -> AuxData:
    # Note that we do not care about the actual backend but rather about
    # the methds inherited from `AbstractBackend`.
    # Small config hack, by writing a dict into config file for password retrieval.
    rs = Script(1, "nobody", dbname="nobody",
                CDB_DATABASE_ROLES="{'nobody': 'nobody'}").rs()
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
        rs=rs, core=core,
        PsycoJson=PsycoJson,
        seq_id_tables=seq_id_tables,
        cyclic_references=cyclic_references,
        constant_replacements=constant_replacements,
        entry_replacements=entry_replacements,
        xss_field_excludes=xss_field_excludes,
        xss_table_excludes=xss_table_excludes,
    )


def build_commands(data: CdEDBObject, aux: AuxData, xss: str) -> List[str]:
    commands: List[str] = []

    # Start off by resetting the sequential ids to 1.
    commands.extend("ALTER SEQUENCE IF EXISTS {}_id_seq RESTART WITH 1;"
                    .format(table) for table in aux["seq_id_tables"])

    # Prepare insert statements for the tables in the source file.
    for table, table_data in data.items():
        # Skip tables that have no data.
        if not table_data:
            continue

        # The following is similar to `cdedb.AbstractBackend.sql_insert_many
        # But we fill missing keys with None isntead of giving an error.
        key_set = set(chain.from_iterable(e.keys() for e in table_data))
        for k in aux["entry_replacements"].get(table, {}).keys():
            key_set.add(k)

        # Remove fileds causing cyclic references. These will be handled later.
        key_set -= set(aux["cyclic_references"].get(table, {}))

        # Convert the keys to a tuple to ensure consistent ordering.
        keys = tuple(key_set)
        # FIXME more precise type
        params: List[Any] = []
        for entry in table_data:
            for k in keys:
                if k not in entry:
                    entry[k] = None
                if isinstance(entry[k], dict):
                    entry[k] = aux["PsycoJson"](entry[k])
                elif isinstance(entry[k], str) and xss:
                    if (table not in aux["xss_table_excludes"]
                            and k not in aux['xss_field_excludes']):
                        entry[k] = entry[k] + xss
            for k, f in aux["entry_replacements"].get(table, {}).items():
                entry[k] = f(entry)
            params.extend(entry[k] for k in keys)

        # Create len(data) many row placeholders for len(keys) many values.
        value_list = ",\n".join(("({})".format(", ".join(("%s",) * len(keys))),)
                                * len(table_data))
        query = "INSERT INTO {table} ({keys}) VALUES {value_list};".format(
            table=table, keys=", ".join(keys), value_list=value_list)
        # noinspection PyProtectedMember
        params = tuple(aux["core"]._sanitize_db_input(p) for p in params)

        # This is a bit hacky, but it gives us access to a psycopg2.cursor
        # object so we can let psycopg2 take care of the heavy lifting
        # regarding correctly inserting the parameters into the SQL query.
        with aux["rs"].conn as conn:
            with conn.cursor() as cur:
                commands.append(cur.mogrify(query, params).decode("utf8"))

    # Now we update the tables to fix the cyclic references we skipped earlier.
    for table, refs in aux["cyclic_references"].items():
        for entry in data[table]:
            for ref in refs:
                if entry.get(ref):
                    query = "UPDATE {} SET {} = %s WHERE id = %s;".format(
                        table, ref)
                    params = (entry[ref], entry["id"])
                    with aux["rs"].conn as conn:
                        with conn.cursor() as cur:
                            commands.append(
                                cur.mogrify(query, params).decode("utf8"))

    # Here we set all sequential ids to start with 1001, so that
    # ids are consistent when running the test suite.
    commands.extend("SELECT setval('{}_id_seq', 1000);".format(table)
                    for table in aux["seq_id_tables"])

    # Lastly we do some string replacements to cheat in SQL-syntax like `now()`:
    ret = []
    for cmd in commands:
        for k, v in aux["constant_replacements"].items():
            cmd = cmd.replace(k, v)
        ret.append(cmd)

    return ret


def main() -> None:
    # Import filelocations from commandline.
    parser = argparse.ArgumentParser(
        description="Generate an SQL-file to insert sample data from a "
                    "JSON-file.")
    parser.add_argument(
        "-i", "--infile",
        default="/cdedb2/tests/ancillary_files/sample_data.json")
    parser.add_argument(
        "-o", "--outfile", default="/tmp/sample_data.sql")
    parser.add_argument("-x", "--xss", default="")
    args = parser.parse_args()

    with open(args.infile) as f:
        data = json.load(f)

    assert isinstance(data, dict)
    aux = prepare_aux(data)
    commands = build_commands(data, aux, args.xss)

    with open(args.outfile, "w") as f:
        for cmd in commands:
            print(cmd, file=f)


if __name__ == '__main__':
    main()
