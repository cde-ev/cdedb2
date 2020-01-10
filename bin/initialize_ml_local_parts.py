#!/usr/bin/env python3

import sys

sys.path.insert(0, "/cdedb2/")
from cdedb.script import setup, make_backend
from cdedb.database.connection import Atomizer
import cdedb.database.constants as const
from cdedb.common import ProxyShim
# Configuration

rs = setup(persona_id=-1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")

# prepare backends

ml = make_backend("ml", proxy=False)

# Start of actual script.

with Atomizer(rs()):
    query = "ALTER TABLE ml.mailinglists ADD COLUMN local_part varchar"

    ml.query_exec(rs(), query, tuple())

    query = "SELECT address, id FROM ml.mailinglists"

    data = ml.query_all(rs(), query, tuple())

    for datum in data:
        query = "uPDATE ml.mailinglists SET local_part = %s WHERE id = %s"
        ml.query_exec(rs(), query, (datum["address"].split("@")[0], datum["id"]))

    query = "SELECT local_part, address FROM ml.mailinglists"
    data = ml.query_all(rs(), query, tuple())

    from pprint import pprint
    pprint(data)

    query = ("ALTER TABLE ml.mailinglists ALTER COLUMN local_part SET NOT NULL;"
             "ALTER TABLE ml.mailinglists ADD CONSTRAINT local_part_unique UNIQUE (local_part)")
    ml.query_exec(rs(), query, tuple())
