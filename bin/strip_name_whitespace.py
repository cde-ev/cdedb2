#!/usr/bin/env python3

from cdedb.backend.core import CoreBackend
from cdedb.common import CdEDBObject
from cdedb.script import Script

s = Script(dbuser="cdb")
rs = s.rs()

core: CoreBackend = s.make_backend("core", proxy=False)

change_note = "Whitespace aus Namen entfernt"

updated = 0
persona_id = None
with s:
    while persona_id := core.next_persona(
            rs, persona_id, is_member=None, is_archived=False,
    ):
        persona = core.get_persona(rs, persona_id)

        update: CdEDBObject = {}
        for k in ('given_names', 'family_name', 'display_name'):
            old = persona[k]
            if persona[k] != (new := " ".join(persona[k].split()).strip()):
                update[k] = persona[k] = new
                print(f"({persona_id})[{k[0]}]: {old!r} -> {new!r}")

        if update:
            update['id'] = persona_id
            core.set_persona(
                rs, update, may_wait=False, change_note=change_note,
                automated_change=True,
            )
            updated += 1

    print(f"Updated {updated} personas.")
