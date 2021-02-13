import argparse
import datetime
import json
import re
import collections

from typing import Dict, Any, Tuple

from cdedb.common import CustomJSONEncoder, nearly_now, xsorted
from cdedb.script import make_backend, setup, MockRequestState
from cdedb.backend.core import CoreBackend

sort_table_by = {
    "ml.subscription_states": "mailinglist_id",
    "ml.whitelist": "mailinglist_id",
    "ml.moderators": "mailinglist_id",
    "assembly.presiders": "assembly_id",
    "assembly.attendees": "assembly_id",
    "assembly.voter_register": "ballot_id",
    "assembly.votes": "ballot_id",
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


def dump_sql_data(rs: MockRequestState, core: CoreBackend
                  ) -> Dict[str, Tuple[Dict[str, Any], ...]]:
    # extract the tables to be created from the database tables
    with open("/cdedb2/cdedb/database/cdedb-tables.sql", "r") as f:
        tables = [table.group('name')
                  for table in re.finditer(r'CREATE TABLE\s(?P<name>\w+\.\w+)', f.read())]

    full_sample_data = {}
    reference_frame = nearly_now(delta=datetime.timedelta(days=30))

    for table in tables:
        query = f"SELECT * FROM {table} ORDER BY {sort_table_by.get(table, 'id')}"
        entities = core.query_all(rs, f"SELECT * FROM {table} ORDER BY id", ())  # type: ignore
        if table in ignored_tables:
            entities = tuple(dict())
        print(f"{query:60} ==> {len(entities):3}", "" if entities else "!")
        sorted_entities = list()
        for entity in xsorted(entities, key=lambda x: x[sort_table_by.get(table, 'id')]):
            sorted_entity = collections.OrderedDict()
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
    rs = setup(1, "cdb_admin", "9876543210abcdefghijklmnopqrst")()
    core = make_backend("core", proxy=False)

    sample_data = dump_sql_data(rs, core)

    with open(args.outfile, "w") as f:
        json.dump(sample_data, f, cls=CustomJSONEncoder, indent=4, ensure_ascii=False)


if __name__ == '__main__':
    main()
