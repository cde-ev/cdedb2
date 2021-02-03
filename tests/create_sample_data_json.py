import datetime
import json
import re

from cdedb.common import CustomJSONEncoder, nearly_now
from cdedb.script import make_backend, setup

rs = setup(1, "cdb_admin", "9876543210abcdefghijklmnopqrst")()

core = make_backend("core", proxy=False)


# extract the tables to be created from the database tables
with open("/cdedb2/cdedb/database/cdedb-tables.sql", "r") as f:
    tables = [table.group('name')
              for table in re.finditer(r'CREATE TABLE\s(?P<name>\w+\.\w+)', f.read())]


full_sample_data = {}

# mark some tables which shall not be filled with information extracted from the
# database.
ignored_tables = {
    "core.sessions"
}

# mark some columns which shall not be filled with information extracted from the
# database, meanly because they will be filled at runtime in create_sample_data_sql.py
ignored_columns = {
    "core.personas": {"fulltext"},
}

# mark some columns which shall not be filled with information extracted from the
# database, because they can be filled by sql automatically.
implicit_columns = {
    "core.log": {"id"},
    "cde.finance_log": {"id"},
    "cde.log": {"id"},
    "past_event.participants": {"id"},
    "past_event.log": {"id"},
    "event.log": {"id"},
    "assembly.presiders": {"id"},
    "assembly.attendees": {"id"},
    "assembly.voter_register": {"id"},
    "assembly.votes": {"id"},
    "assembly.log": {"id"},
    "ml.subscription_states": {"id"},
    "ml.subscription_addresses": {"id"},
    "ml.whitelist": {"id"},
    "ml.moderators": {"id"},
    "ml.log": {"id"},
}

for table in tables:
    query = f"SELECT * FROM {table} ORDER BY id"
    entities = core.query_all(rs, f"SELECT * FROM {table} ORDER BY id", ())
    if table in ignored_tables:
        entities = list()
    print(f"{query:60} ==> {len(entities):3}", "" if entities else "!")
    for entity in entities:
        # Since we want to modify the list in-place, we have to iterate in this way.
        for field, value in list(entity.items()):
            if isinstance(value, datetime.datetime) and value == nearly_now():
                entity[field] = "---now---"
            if field in ignored_columns.get(table, {}):
                entity[field] = None
            if field in implicit_columns.get(table, {}):
                del entity[field]
    full_sample_data[table] = entities

with open("/cdedb2/tests/ancillary_files/sample_data.json", "w") as f:
    json.dump(full_sample_data, f, cls=CustomJSONEncoder,
              indent=4, ensure_ascii=False)
