#!/usr/bin/env python3
from functools import partial

from cdedb.common import PERSONA_ALL_FIELDS
from cdedb.script import Script, CoreBackend
from cdedb.validation import validate_assert_optional
import cdedb.validationtypes as vtypes

script = Script(dbuser="cdb")
rs = script.rs()

core: CoreBackend = script.make_backend("core", proxy=False)
phone = partial(validate_assert_optional, vtypes.Phone, _ignore_warnings=True)

phone_fields = ('telephone', 'mobile')

p_id = None
count = {"personas": 0, "changelog": 0}
with script:
    while p_id := core.next_persona(rs, p_id, is_member=None, is_archived=None):
        # Adjust stored values in personas table.
        persona = core.get_total_persona(rs, p_id)
        if any(persona[k] for k in phone_fields):
            update = {
                'id': p_id,
                **{k: phone(persona[k]) for k in phone_fields},
            }
            # print("\n".join(f"{persona[k]} -> {update[k]}" for k in phone_fields))
            count["personas"] += 1
            core.sql_update(rs, "core.personas", update)

        # Adjust stored values in changelog table.
        changelog = core.sql_select(
            rs, "core.changelog", PERSONA_ALL_FIELDS, (p_id,), "persona_id")
        for entry in changelog:
            if any(entry[k] for k in phone_fields):
                update = {
                    'id': entry['id'],
                    **{k: phone(entry[k]) for k in phone_fields},
                }
                # print("\n".join(f"{entry[k]} -> {update[k]}" for k in phone_fields))
                count["changelog"] += 1
                core.sql_update(rs, "core.changelog", update)

    for k, c in count.items():
        print(f"Updated {c} entries in the {k} table.")
