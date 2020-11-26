#!/usr/bin/env python3

from cdedb.script import setup, make_backend
from cdedb.database.connection import Atomizer
from cdedb.ml_type_aux import get_type, get_full_address
import cdedb.database.constants as const
# Configuration

rs = setup(persona_id=1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")

DRY_RUN = True

# prepare backends

ml = make_backend("ml", proxy=False)

# Start of actual script.

print("\n"*2)

with Atomizer(rs()):
    query = "ALTER TABLE ml.mailinglists ADD COLUMN local_part varchar"

    ml.query_exec(rs(), query, tuple())

    query = "SELECT address, id FROM ml.mailinglists"

    data = ml.query_all(rs(), query, tuple())

    for datum in data:
        query = "UPDATE ml.mailinglists SET local_part = %s WHERE id = %s"
        ml.query_exec(rs(), query, (datum["address"].split("@")[0], datum["id"]))

    query = ("ALTER TABLE ml.mailinglists ALTER COLUMN local_part SET NOT NULL;"
             "ALTER TABLE ml.mailinglists ADD CONSTRAINT local_part_unique UNIQUE (local_part)")
    ml.query_exec(rs(), query, tuple())

    query = "ALTER TABLE ml.mailinglists ADD COLUMN domain integer DEFAULT 1"
    ml.query_exec(rs(), query, tuple())

    query = "SELECT id, local_part, address, ml_type FROM ml.mailinglists"
    data = ml.query_all(rs(), query, tuple())

    for datum in data:
        atype = get_type(datum['ml_type'])

        for k, v in const._DOMAIN_STR_MAP.items():
            if datum['address'].split('@')[1] == v:
                domain = k
                break
        else:
            domain = atype.domains[0]
            print("Domain not found, defaulting to: {}".format(domain))
        setter = {
            'id': datum['id'],
            'domain': domain,
        }
        setter['address'] = get_full_address(dict(datum, **setter))
        ml.sql_update(rs(), "ml.mailinglists", setter)

    query = "ALTER TABLE ml.mailinglists ALTER COLUMN domain SET NOT NULL"
    ml.query_exec(rs(), query, tuple())
    query = "ALTER TABLE ml.mailinglists ALTER COLUMN domain DROP DEFAULT"
    ml.query_exec(rs(), query, tuple())

    query = "SELECT local_part, domain, address FROM ml.mailinglists"
    data = ml.query_all(rs(), query, tuple())

    print("\n"*2)
    print("Please check the following for consistency:\n")
    for datum in data:
        print(datum)
        assert datum['local_part'] + '@' + str(const.MailinglistDomain(datum['domain'])) == datum['address']

    if DRY_RUN:
        print("\n"*2)
        raise ValueError("Aborting due to dry run, please ignore the following exception.")
