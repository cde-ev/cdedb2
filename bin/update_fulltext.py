#!/usr/bin/env python3
"""Generic script to regenerate the fulltext field of a persona after changes.

Should not be archived after use.
"""
from cdedb.common import PERSONA_ALL_FIELDS
from cdedb.script import Script

# config
DRY_RUN = True
CHECK = True

# setup

script = Script(persona_id=-1, dbuser="cdb_admin", dry_run=DRY_RUN)
rs = script.rs()
core = script.make_backend("core", proxy=False)

# work

ALL_FIELDS = PERSONA_ALL_FIELDS + ("fulltext",)
count = 0

with script:
    persona_id = core.next_persona(rs, -1, is_member=None, is_archived=None)
    while persona_id is not None:
        persona = core.retrieve_persona(rs, persona_id, ALL_FIELDS)
        data = {
            'id': persona_id,
            'fulltext': core.create_fulltext(persona)
        }
        code = core.sql_update(rs, "core.personas", data)
        count += code
        if code != 1:
            raise RuntimeError(
                f"Somethings went wrong while updating persona {persona_id}.")
        else:
            print(persona_id, end=" ", flush=True)
        persona_id = core.next_persona(rs, persona_id, is_member=None, is_archived=None)
