#!/usr/bin/env python3
from cdedb.common import ArchiveError
from cdedb.script import make_backend, setup, Script, CoreBackend

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")()

DRY_RUN = True

# Prepare stuff

core: CoreBackend = make_backend("core")

successful = set()
archive_error = set()
other_error = set()

# Execution

with Script(rs, dry_run=DRY_RUN):
    persona_id = core.next_persona(
        rs, persona_id=-1, is_member=False, is_archived=False)
    while persona_id:
        is_archivable = core.is_persona_automatically_archivable(rs, persona_id)
        print(persona_id, is_archivable)
        if is_archivable:
            note = "Automatically archived after prolonged inactivity."
            print(f"Archiving user {persona_id}...")
            try:
                code = core.archive_persona(rs, persona_id, note)
            except ArchiveError as ae:
                print(f"Error: {ae}")
                archive_error.add((persona_id, ae))
            else:
                if code:
                    successful.add(persona_id)
                    print("Success!")
                else:
                    other_error.add(persona_id)
                    print("Error!")

        persona_id = core.next_persona(
            rs, persona_id=persona_id, is_member=False, is_archived=False)

    print(f"Successfully archived {len(successful)} accounts.")
    print(f"{len(archive_error)} archivals failed with an archive error.")
    print(f"{len(other_error)} archivals failed for an unknown reason.")

    print("Here comes a list of archive errors:")
    for persona_id, e in archive_error:
        print(persona_id, e)
        print()
