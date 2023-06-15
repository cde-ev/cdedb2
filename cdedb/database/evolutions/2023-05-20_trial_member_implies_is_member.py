#!/usr/bin/env python3

from cdedb.backend.core import CoreBackend
from cdedb.script import Script

s = Script(dbuser='cdb')

core: CoreBackend = s.make_backend("core", proxy=False)

if s.persona_id < 0:
    raise RuntimeError("Need persona id to create changelog entries.")

with s:
    query = ("SELECT id FROM core.personas"
             " WHERE is_member IS FALSE AND trial_member IS TRUE;")
    print("Strip trial membership from all non-members", end="", flush=True)
    entries = core.query_all(s.rs(), query, ())

    step = (len(entries) // 10) if len(entries) > 20 else 1
    for i, e in enumerate(entries):
        data = {
            'id': e['id'],
            'trial_member': False,
        }
        core.set_persona(
            s.rs(), data, allow_specials=("membership", "purge"), automated_change=True,
            change_note="Entferne Probemitgliedschaft von Nicht-Mitgliedern.")

        if i % step == 0:
            print(".", end="", flush=True)
    print()

    # Add database constraint
    query = """
        ALTER TABLE core.personas ADD CONSTRAINT
        personas_trial_member_implicits CHECK (NOT trial_member OR is_member);
    """
    core.query_exec(s.rs(), query, ())
    print("Added new constraint.")
