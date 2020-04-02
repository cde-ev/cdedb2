import sys
import json
import datetime
import collections
import decimal

from pprint import pprint

sys.path.insert(0, "/cdedb2")

from cdedb.script import setup, make_backend
from cdedb.common import CustomJSONEncoder
from test.common import nearly_now

rs = setup(1, "cdb_admin", "9876543210abcdefghijklmnopqrst")()

core = make_backend("core", proxy=False)

# The following code was initially used to generate the list below.
# However to preserve referential integrity, the order of the tables hab to
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

query = "SELECT table_schema, table_name, column_name " \
        "FROM information_schema.columns WHERE data_type = %s"
params = ("jsonb",)
data = core.query_all(rs, query, params)

JSON_FIELDS = {
    (e["table_schema"] + "." + e["table_name"], e["column_name"])
    for e in data
}

full_sample_data = collections.OrderedDict()

for table in tables:
    query = "SELECT * FROM {} ORDER BY id".format(table)
    params = tuple()
    data = core.query_all(rs, query, params)
    print(query, len(data))
    for e in data:
        for k, v in e.items():
            if (table, k) in JSON_FIELDS:
                e[k] = json.dumps(v)
            if isinstance(v, datetime.datetime):
                if v == nearly_now():
                    e[k] = "---now---"
    full_sample_data[table] = data
    if not data:
        print(table)

with open("/cdedb2/sample_data.json", "w", encoding="utf8") as f:
    f.write(json.dumps(full_sample_data, cls=CustomJSONEncoder, indent=4))
