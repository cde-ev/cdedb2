#!/usr/bin/env python3
import cProfile
import datetime
import timeit
from typing import NamedTuple, Set

from cdedb.common import now
from cdedb.script import make_backend, setup, Script

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

user_rs = rs(executing_admin_id)
DRY_RUN = True

# Prepare stuff

ml = make_backend("ml", proxy=False)

# Execution

with Script(user_rs, dry_run=DRY_RUN):
    def run(n: int) -> None:
        for _ in range(n):
            ml_ids = ml.list_mailinglists(user_rs)
            for ml_id in ml_ids:
                ml.write_subscription_states(user_rs, ml_id)
            # ml.write_subscription_states(user_rs, ml_ids)

    cProfile.run("run(1)", "write_subscription_states_production.prof")
