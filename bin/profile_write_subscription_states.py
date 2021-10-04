#!/usr/bin/env python3
import cProfile

from cdedb.script import Script

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = -1

# Prepare stuff
script = Script(persona_id=executing_admin_id, dbuser="cdb_admin")
user_rs = script.rs()

ml = script.make_backend("ml", proxy=False)

# Execution

with script:
    def run(n: int) -> None:
        for _ in range(n):
            ml_ids = ml.list_mailinglists(user_rs)
            # for ml_id in ml_ids:
            #     ml.write_subscription_states(user_rs, ml_id)
            ml.write_subscription_states(user_rs, ml_ids)

    cProfile.run("run(1)", "/cdedb2/write_subscription_states_production.prof")
