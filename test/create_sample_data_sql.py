import json
import sys
from itertools import chain

sys.path.insert(0, "/cdedb2")

from cdedb.common import now
from cdedb.script import setup, make_backend
from cdedb.backend.common import AbstractBackend

infile = "/cdedb2/test/ancillary_files/sample_data.json"
outfile = "/tmp/sample_data.sql"
if len(sys.argv) >= 2:
    infile = sys.argv[1]
if len(sys.argv) >= 3:
    outfile = sys.argv[2]

rs = setup(1, "cdb_admin", "9876543210abcdefghijklmnopqrst")()
core = make_backend("core", proxy=False)

with open(infile, "r", encoding="utf8") as f:
    data = json.load(f)

# TODO Decide: read these tables dynamically or provide a hardcoded list?
query = "SELECT table_schema, table_name FROM information_schema.columns " \
        "WHERE column_name = %s AND column_default IS NOT NULL;"
params = ("id", )
seq_id_tables = [
    e["table_schema"] + "." + e["table_name"]
    for e in core.query_all(rs, query, params)
]

CYCLIC_REFERENCES = {
    "event.events": ("lodge_field", "course_room_field", "reserve_field"),
}


CONSTANT_REPLACEMENTS = {
    "'---now---'": "now()",
}


# Mapping of (table, column), to replacement (function, arguments)
ENTRY_REPLACEMENTS = {
    ("core.personas", "full_text"): lambda e, k: core.create_fulltext(e),
    ("core.changelog", "full_text"): lambda e, k: core.create_fulltext(e),
}

commands = []
commands.extend("ALTER SEQUENCE {}_id_seq RESTART WITH 1;".format(table)
                for table in seq_id_tables)

for table, table_data in data.items():
    if not table_data:
        print(table)
        continue

    # The following is similar to `cdedb.AbstractBackend.sql_insert_many
    # But we fill missing keys with None isntead of giving an error.
    key_set = set(chain.from_iterable(e.keys() for e in table_data))
    # We have to special case these fields, because they have cyclic references.
    if table in CYCLIC_REFERENCES:
        key_set -= set(CYCLIC_REFERENCES[table])
    keys = tuple(key_set)
    params = []
    for entry in table_data:
        for k in keys:
            if k not in entry:
                entry[k] = None
            if (table, k) in ENTRY_REPLACEMENTS:
                entry[k] = ENTRY_REPLACEMENTS[(table, k)](entry, k)
        params.extend(entry[k] for k in keys)
    # Create len(data) many row placeholders for len(keys) many values.
    value_list = ", ".join(("({})".format(", ".join(("%s",) * len(keys))),)
                           * len(table_data))
    query = "INSERT INTO {table} ({keys}) VALUES {value_list};".format(
        table=table, keys=", ".join(keys), value_list=value_list)
    params = tuple(AbstractBackend._sanitize_db_input(p) for p in params)

    with rs.conn as conn:
        with conn.cursor() as cur:
            commands.append(cur.mogrify(query, params).decode("utf8"))

for table in CYCLIC_REFERENCES:
    for entry in data[table]:
        for ref in CYCLIC_REFERENCES[table]:
            if entry.get(ref):
                query = "UPDATE {} SET {} = %s WHERE id = %s;".format(
                    table, ref)
                params = (entry[ref], entry["id"])
                with rs.conn as conn:
                    with conn.cursor() as cur:
                        commands.append(
                            cur.mogrify(query, params).decode("utf8"))

commands.extend("SELECT setval('{}_id_seq', 1000);".format(table)
                for table in seq_id_tables)

# print("\n".join(commands))

with open(outfile, "w", encoding="utf8") as f:
    for cmd in commands:
        for k, v in CONSTANT_REPLACEMENTS.items():
            cmd = cmd.replace(k, v)
        f.write(cmd)
        f.write("\n")
