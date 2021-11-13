#!/usr/bin/env python3
from functools import partial

import cdedb.validationtypes as vtypes
from cdedb.common import CdEDBObject
from cdedb.script import CoreBackend, Script
from cdedb.validation import validate_assert_optional

script = Script(persona_id=1, dbuser="cdb_admin")
rs = script.rs()

core: CoreBackend = script.make_backend("core", proxy=False)
phone = partial(validate_assert_optional, vtypes.Phone, ignore_warnings=True)

phone_fields = ('telephone', 'mobile')
msg = "Normalisierung von Telefonnummern"

p_id = None
count = 0
with script:
    while p_id := core.next_persona(rs, p_id, is_member=None, is_archived=None):
        # Adjust stored values in personas table.
        persona = core.get_total_persona(rs, p_id)
        if any(persona[k] for k in phone_fields):
            update: CdEDBObject = {
                'id': p_id,
                **{k: phone(persona[k]) for k in phone_fields},
            }
            core.set_persona(rs, update, change_note=msg, automated_change=True)
            count += 1
            print("\n".join(f"{persona[k]} -> {update[k]}" for k in phone_fields))

    print(f"Updated {count} entries.")
