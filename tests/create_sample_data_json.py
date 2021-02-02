import datetime
import json
import re
import sys

sys.path.insert(0, "/cdedb2/")

from cdedb.common import CustomJSONEncoder
from cdedb.script import make_backend, setup
from tests.common import nearly_now

rs = setup(1, "cdb_admin", "9876543210abcdefghijklmnopqrst")()

core = make_backend("core", proxy=False)

# The following code was initially used to generate the list below.
# However to preserve referential integrity, the order of the tables had to
# be slightly adjusted, so we cannot keep the dynamic list of table.

# query = "SELECT schemaname, tablename " \
#         "FROM pg_catalog.pg_tables " \
#         "WHERE schemaname != 'pg_catalog' " \
#         "AND schemaname != 'information_schema'"
# params = tuple()
#
# table_data = core.query_all(rs, query, params)
#
# tables = []
# for table in table_data:
#     tables.append(table["schemaname"] + "." + table["tablename"])
#
# # pprint(tables)


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
    entities = list(core.query_all(rs, f"SELECT * FROM {table} ORDER BY id", ()))
    if table in ignored_tables:
        entities = list()
    print(f"{query:60} ==> {len(entities):3}", "" if entities else "!")
    # Since we want to modify the list in-place, we have to iterate in this way.
    for i in range(len(entities)):
        for field, value in list(entities[i].items()):
            if field in implicit_columns.get(table, {}):
                del entities[i][field]
            if field in ignored_columns.get(table, {}):
                entities[i][field] = None
            if isinstance(value, datetime.datetime) and value == nearly_now():
                entities[i][field] = "---now---"
    full_sample_data[table] = entities

with open("/cdedb2/tests/ancillary_files/sample_data.json", "w") as f:
    json.dump(full_sample_data, f, cls=CustomJSONEncoder,
              indent=4, ensure_ascii=False)
