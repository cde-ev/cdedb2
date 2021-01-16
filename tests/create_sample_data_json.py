import datetime
import json

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

tables = [
    'core.meta_info',
    'core.cron_store',
    'core.personas',
    'core.changelog',
    'core.privilege_changes',
    'core.genesis_cases',
    'core.sessions',
    'core.quota',
    'core.log',
    'cde.org_period',
    'cde.expuls_period',
    'cde.lastschrift',
    'cde.lastschrift_transactions',
    'cde.finance_log',
    'cde.log',
    'past_event.institutions',
    'past_event.events',
    'past_event.courses',
    'past_event.participants',
    'past_event.log',
    'event.events',
    'event.orgas',
    'event.field_definitions',
    'event.questionnaire_rows',
    'event.event_parts',
    'event.course_tracks',
    'event.courses',
    'event.course_segments',
    'event.lodgement_groups',
    'event.lodgements',
    'event.registrations',
    'event.registration_parts',
    'event.registration_tracks',
    'event.course_choices',
    'event.log',
    'assembly.assemblies',
    'assembly.attendees',
    'assembly.ballots',
    'assembly.candidates',
    'assembly.attachments',
    'assembly.votes',
    'assembly.voter_register',
    'assembly.log',
    'ml.mailinglists',
    'ml.moderators',
    'ml.whitelist',
    'ml.subscription_states',
    'ml.subscription_addresses',
    'ml.log',
]


full_sample_data = {}

# mark some columns which shall not be filled with information extracted from the
# database, meanly because they will be filled at runtime in create_sample_data_sql.py
ignored_columns = {
    "core.personas":
        {
            "fulltext",
        },
}

for table in tables:
    query = f"SELECT * FROM {table} ORDER BY id"
    entities = core.query_all(rs, f"SELECT * FROM {table} ORDER BY id", ())
    print(f"{query:60} ==> {len(entities):3}", "" if entities else "!")
    for entity in entities:
        for field, value in entity.items():
            if isinstance(value, datetime.datetime) and value == nearly_now():
                entity[field] = "---now---"
            if table in ignored_columns and field in ignored_columns[table]:
                entity[field] = None
    full_sample_data[table] = entities

with open("/cdedb2/tests/ancillary_files/sample_data.json", "w") as f:
    json.dump(full_sample_data, f, cls=CustomJSONEncoder,
              indent=4, ensure_ascii=False)
