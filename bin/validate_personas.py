#!/usr/bin/env python3
import sys
from typing import Optional

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common.sorting import xsorted
from cdedb.script import Script

# Prepare stuff

script = Script(dbuser="cdb_persona")
rs = script.rs()
core = script.make_backend("core")

def _print_error(persona_id: int, e: Exception) -> None:
    print("-" * 80, file=sys.stderr)
    print(f"Error for persona {persona_id}:", file=sys.stderr)
    print(e.__class__, file=sys.stderr)
    print(e, file=sys.stderr)

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
            _print_error(persona_id, e)
            errors += 1
            continue

        # Validate event data if applicable
        if not persona['is_event_realm']:
            continue

        persona = core.get_event_user(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona)
        except Exception as e:
            _print_error(persona_id, e)
            errors += 1
            continue

        # Validate cde/total data if applicable
        if not persona['is_cde_realm']:
            continue

        persona = core.get_total_persona(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona)
        except Exception as e:
            _print_error(persona_id, e)
            errors += 1
            continue

        # Validate consistency of changelog with persona state
        history = core.changelog_get_history(rs, persona_id, generations=None)

        for generation in xsorted(history.values(), key=lambda x: x['generation'],
                                  reverse=True):
            if generation['code'] == const.MemberChangeStati.committed:
                if diff := [key for key in persona if persona[key] != generation[key]]:
                    print("-" * 80, file=sys.stderr)
                    print(f"Error for persona {persona_id}:", file=sys.stderr)
                    errors += 1
                    for key in diff:
                        print(f"Changelog inconsistent for field {key}: {persona[key]}"
                              f" != {generation[key]}", file=sys.stderr)
                break
        else:
            print("-" * 80, file=sys.stderr)
            print(f"No commited state found for persona {persona_id}.", file=sys.stderr)
            errors += 1

    if errors:
        print(f"There were {errors} errors.", file=sys.stderr)
    else:
        print("All personas were validated successfully.")
