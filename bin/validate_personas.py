#!/usr/bin/env python3
import sys
from typing import List, Optional, Tuple

import cdedb.common.validation.types as vtypes
from cdedb.backend.core import CoreBackend
from cdedb.common.validation.validate import validate_check as check
from cdedb.script import Script

# Prepare stuff

script = Script(dbuser="cdb_persona")
rs = script.rs()
core: CoreBackend = script.make_backend("core")

# Execution

with script:
    persona_id: Optional[int] = -1
    total_errors = 0
    while True:
        persona_id = core.next_persona(
            rs, persona_id=persona_id, is_member=None, is_archived=False)
        errors: List[Tuple[Optional[str], Exception]] = []

        if not persona_id:
            break

        # Validate ml data
        persona = core.get_ml_user(rs, persona_id)

        _, errs = check(vtypes.Persona, persona, ignore_warnings=True)
        errors.extend(errs)

        # Validate event data if applicable
        if persona['is_event_realm']:
            persona = core.get_event_user(rs, persona_id)
            _, errs = check(vtypes.Persona, persona, ignore_warnings=True)
            errors.extend(errs)

        # Validate cde/total data if applicable
        persona = core.get_total_persona(rs, persona_id)
        if persona['is_cde_realm']:
            _, errs = check(vtypes.Persona, persona, ignore_warnings=True)
            errors.extend(errs)

        # Validate consistency of changelog with core.persona
        inconsistencies = core.get_changelog_inconsistencies(rs, persona_id)
        if inconsistencies is None:
            errors.append(("Changelog", RuntimeError(
                f"No committed state found.")))
        elif inconsistencies is not []:
            for key in inconsistencies:
                errors.append(("Changelog", RuntimeError(
                    f"Changelog inconsistent for field {key}")))

        # Print all errors for this persona
        if errors:
            print("-" * 80, file=sys.stderr)
            print(f"Error for persona {persona_id}:", file=sys.stderr)
            for field, error in errors:
                print(f"{error.__class__}: {error} ({field})", file=sys.stderr)
            total_errors += 1

    if total_errors:
        print(f"\nThere were {total_errors} errors.", file=sys.stderr)
    else:
        print("All personas were validated successfully.")
