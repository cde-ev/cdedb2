#!/usr/bin/env python3
from typing import Optional

from cdedb.script import make_backend, setup, Script, CoreBackend
import cdedb.validationtypes as vtypes
from cdedb.backend.common import affirm_validation_typed as affirm

# Configuration

# This script does not write log entries and thus does not need a valid id.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_persona",
           dbpassword="abcdefghijklmnopqrstuvwxyzabcd")()

# Prepare stuff

core: CoreBackend = make_backend("core")

# Execution

with Script(rs, dry_run=False):
    persona_id: Optional[int] = -1
    while True:
        persona_id = core.next_persona(
            rs, persona_id=persona_id, is_member=None, is_archived=False)

        if not persona_id:
            break

        # Validate ml data
        persona = core.get_ml_user(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona, _ignore_warnings=True)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            continue

        # Validate event data if applicable
        if not persona['is_event_realm']:
            continue

        persona = core.get_event_user(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona, _ignore_warnings=True)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            continue

        # Validate cde/total data if applicable
        if not persona['is_cde_realm']:
            continue

        persona = core.get_total_persona(rs, persona_id)
        try:
            affirm(vtypes.Persona, persona, _ignore_warnings=True)
        except Exception as e:
            print("-" * 80)
            print(f"Error for persona {persona_id}:")
            print(e.__class__)
            print(e)
            continue
