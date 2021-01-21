# type: ignore

import argparse
import json
import sys
from itertools import chain


def read_input(infile):
    with open(infile, "r", encoding="utf8") as f:
        ret = json.load(f)

    return ret


def prepare_aux(data):
    ret = {}

    # Set up the database connection.
    sys.path.insert(0, "/cdedb2")

    from cdedb.backend.common import PsycoJson
    from cdedb.backend.core import CoreBackend
    from cdedb.script import setup

    # Note that we do not care about the actual backend but rather about
    # the methds inherited from `AbstractBackend`.
    rs_maker = setup(1, "nobody", "nobody", dbname="nobody")
    ret["rs"] = rs_maker()
    ret["core"] = CoreBackend  # No need to instantiate, we only use statics.
    ret["PsycoJson"] = PsycoJson

    # Extract some data about the databse tables using the database connection.

    # The following is a list of tables to that do NOT have sequential ids:
    non_seq_id_tables = [
        "cde.org_period",
        "cde.expuls_period",
    ]

    ret["seq_id_tables"] = [t for t in data if t not in non_seq_id_tables]
    # Prepare some constants for special casing.

    # This maps full table names to a list of column names in that table that
    # require special care, because they contain cycliy references.
    # They will be removed from the initial INSERT and UPDATEd later.
    ret["cyclic_references"] = {
        "event.events": ("lodge_field", "course_room_field", "camping_mat_field"),
    }

    # This contains a list of replacements performed on the resulting SQL
    # code at the very end. Note that this is the only way to actually insert
    # SQL-syntax. We use it to alway produce a current timestamp, because a
    # fixed timestamp from the start of a test suite won't do.
    ret["constant_replacements"] = {
        "'---now---'": "now()",
    }

    # For every table we may map one of it's columns to a function which
    # dynamically generates data to insert.
    # The function will get the entire row as a argument.
    ret["entry_replacements"] = {
        "core.personas":
            {
                "fulltext": ret["core"].create_fulltext,
            },
    }

    return ret


def build_commands(data, aux):
    commands = []

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
        params = []
        for entry in table_data:
            for k in keys:
                if k not in entry:
                    entry[k] = None
                if isinstance(entry[k], dict):
                    entry[k] = aux["PsycoJson"](entry[k])
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


def write_output(commands, outfile):
    with open(outfile, "w", encoding="utf8") as f:
        for cmd in commands:
            f.write(cmd)
            f.write("\n")


def main():
    # Import filelocations from commandline.
    parser = argparse.ArgumentParser(
        description="Generate an SQL-file to insert sample data from a "
                    "JSON-file.")
    parser.add_argument(
        "-i", "--infile",
        default="/cdedb2/tests/ancillary_files/sample_data.json")
    parser.add_argument(
        "-o", "--outfile", default="/tmp/sample_data.sql")
    args = parser.parse_args()

    data = read_input(args.infile)
    aux = prepare_aux(data)
    commands = build_commands(data, aux)
    write_output(commands, args.outfile)


if __name__ == '__main__':
    main()
