#!/usr/bin/env python3
"""Generic script to regenerate the fulltext field of a persona after changes.

Should not be archived after use.
"""
from cdedb.backend.core import CoreBackend
from cdedb.script import Script

# setup

script = Script(persona_id=-1, dbuser="cdb_admin")
rs = script.rs()
core: CoreBackend = script.make_backend("core")

# parameters

log_table = ""
log_id = 0
new_message = ""

# work

with script:
    if not log_table:
        raise RuntimeError("Need to specify log table")
    core.redact_log(rs, log_table, log_id, new_message)
