#!/usr/bin/env python3
from cdedb.common import ArchiveError
from cdedb.script import make_backend, setup, Script

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = 1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

DRY_RUN = True

# Prepare stuff

core = make_backend("core")

# Execution

with Script(rs(), dry_run=DRY_RUN):
    persona_id = core.next_persona(rs(), persona_id=-1, is_member=False)
    while persona_id:
        is_archivable = core.is_persona_automatically_archivable(rs(), persona_id)
        print(persona_id, is_archivable)
        if is_archivable:
            note = "Automatically archived after prolonged inactivity."
            print(f"Archiving user {persona_id}...")
            try:
                code = core.archive_persona(rs(), persona_id, note)
            except ArchiveError as e:
                print(f"Error: {e}")
            else:
                if code:
                    print("Success!")
                else:
                    print("Error!")

        persona_id = core.next_persona(rs(), persona_id=persona_id, is_member=False)
