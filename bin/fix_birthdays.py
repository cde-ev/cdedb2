#!/usr/bin/env python3
# setup

import datetime

from cdedb.script import Script, make_backend, setup

core = make_backend("core", proxy=False)

# config

rs = setup(persona_id=-1, dbuser="cdb",
           dbpassword="987654321098765432109876543210")()
DRY_RUN = True

# constants
unknown = datetime.date.min
tables = {"core.personas", "core.changelog"}
# work

count = 0
with Script(rs, dry_run=DRY_RUN):
    for t in tables:
        query = (f"UPDATE {t} SET birthday = '{unknown}'"
                 " WHERE is_event_realm = TRUE"
                 " AND (birthday = '-Infinity' OR birthday IS NULL)")
        ret = core.query_exec(rs, query, [])
