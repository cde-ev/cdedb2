#!/usr/bin/env python3
# setup

import sys

sys.path.insert(0, "/cdedb2/")
from cdedb.script import make_backend, setup, Script
import cdedb.database.constants as const
from cdedb.common import PERSONA_CORE_FIELDS

core = make_backend("core", proxy=False)

# config

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")()
DRY_RUN = True

# work

REALM_BITS = ("is_cde_realm", "is_event_realm", "is_assembly_realm",
              "is_ml_realm")
note_appendix = ("\n\nDie Bereiche dieses Nutzers wurden nach der Archivierung"
                 " angepasst. Er sollte daher nicht reaktiviert werden.")
base_update = {realm: True for realm in REALM_BITS}
count = 0
with Script(rs, dry_run=DRY_RUN):
    query = "SELECT id FROM core.personas WHERE is_archived = True"
    persona_ids = {e['id'] for e in core.query_all(rs, query, tuple())}
    personas = core.retrieve_personas(
        rs, persona_ids, PERSONA_CORE_FIELDS + ("notes",))
    for persona in personas.values():
        if all(not persona[realm] for realm in REALM_BITS):
            print(f"Fixing realms, gender, balance and paper_expuls for"
                  f" User {persona['given_names']} {persona['family_name']}"
                  f" ({persona['id']}).")
            update = dict(base_update)
            update['id'] = persona['id']
            update['gender'] = const.Genders.not_specified
            update['balance'] = 0
            update['paper_expuls'] = True
            notes = persona['notes'] if persona['notes'] else ""
            update['notes'] = notes + note_appendix
            core.sql_update(rs, "core.personas", update)
            count += 1

    print(f"{count} of {len(persona_ids)} archived users updated.")
