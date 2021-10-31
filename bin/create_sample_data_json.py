import argparse
import datetime
import json
import re
from typing import Any, Dict, List

from cdedb.common import CustomJSONEncoder, RequestState, nearly_now
from cdedb.script import CoreBackend, Script

# per default, we sort entries in a table by their id. Here we can specify any arbitrary
# columns which should be used as sorting key for the table.
sort_table_by = {
    "ml.subscription_states": ["mailinglist_id", "persona_id"],
    "ml.whitelist": ["mailinglist_id"],
    "ml.moderators": ["mailinglist_id", "persona_id"],
    "assembly.presiders": ["assembly_id", "persona_id"],
    "assembly.attendees": ["assembly_id", "persona_id"],
    "assembly.voter_register": ["ballot_id"],
    "assembly.votes": ["ballot_id", "vote"],
}

# mark some tables which shall not be filled with information extracted from the
# database.
ignored_tables = {
    "core.sessions",
    "core.quota",
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


def dump_sql_data(rs: RequestState, core: CoreBackend
                  ) -> Dict[str, List[Dict[str, Any]]]:
    # extract the tables to be created from the database tables
    with open("/cdedb2/cdedb/database/cdedb-tables.sql", "r") as f:
        tables = [table.group('name')
                  for table in re.finditer(r'CREATE TABLE\s(?P<name>\w+\.\w+)', f.read())]

    # take care that the order is preserved
    full_sample_data = dict()
    reference_frame = nearly_now(delta=datetime.timedelta(days=30))

    for table in tables:
        order = ", ".join(sort_table_by.get(table, []) + ['id'])
        query = f"SELECT * FROM {table} ORDER BY {order}"
        entities = core.query_all(rs, query, ())
        if table in ignored_tables:
            entities = tuple()
        print(f"{query:100} ==> {len(entities):3}", "" if entities else "!")
        sorted_entities = list()
        for entity in entities:
            # take care that the order is preserved
            sorted_entity: Dict[str, Any] = dict()
            for field, value in entity.items():
                if field in implicit_columns.get(table, {}):
                    pass
                elif field in ignored_columns.get(table, {}):
                    sorted_entity[field] = None
                elif isinstance(value, datetime.datetime) and value == reference_frame:
                    sorted_entity[field] = "---now---"
                else:
                    sorted_entity[field] = value
            sorted_entities.append(sorted_entity)

        full_sample_data[table] = sorted_entities

    return full_sample_data


def main() -> None:
    # Import output file location from commandline.
    parser = argparse.ArgumentParser(
        description="Generate a JSON-file from the current state of the database.")
    parser.add_argument(
        "-o", "--outfile", default="/tmp/sample_data.json")
    args = parser.parse_args()

    # Setup rs
    script = Script(dbuser="cdb_admin")
    rs = script.rs()
    core = script.make_backend("core", proxy=False)

    data = dump_sql_data(rs, core)

    with open(args.outfile, "w") as f:
        json.dump(data, f, cls=CustomJSONEncoder, indent=4, ensure_ascii=False)


if __name__ == '__main__':
    main()
