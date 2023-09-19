#!/usr/bin/env python3
"""Generic script to repurge all purged personas.

Should not be archived after use.
"""
from cdedb.backend.common import Silencer
from cdedb.script import Script

# setup

script = Script(persona_id=-1, dbuser="cdb_admin")
rs = script.rs()
core = script.make_backend("core", proxy=False)

# work

with script:
    query = "SELECT id FROM core.personas WHERE is_purged = True"
    persona_ids = {e['id'] for e in core.query_all(rs, query, tuple())}
    for persona_id in persona_ids:
        print(f"Repurging User {persona_id}.")
        with Silencer(rs):
            core.purge_persona(rs, persona_id)
