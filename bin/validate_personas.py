#!/usr/bin/env python3
from typing import Optional

import cdedb.validationtypes as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.script import Script

# Prepare stuff

script = Script(dbuser="cdb_persona")
rs = script.rs()
core = script.make_backend("core")

# Execution

with script:
    persona_id: Optional[int] = -1
    errors = 0
    while True:
        persona_id = core.next_persona(
            rs, persona_id=persona_id, is_member=None, is_archived=False)

        if not persona_id:
            break

        # Validate ml data
        persona = core.get_ml_user(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            errors += 1
            continue

        # Validate event data if applicable
        if not persona['is_event_realm']:
            continue

        persona = core.get_event_user(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            errors += 1
            continue

        # Validate cde/total data if applicable
        if not persona['is_cde_realm']:
            continue

        persona = core.get_total_persona(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            errors += 1
            continue

    if not errors:
        print("All personas were validated successfully.")
