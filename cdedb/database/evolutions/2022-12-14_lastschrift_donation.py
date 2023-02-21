#!/usr/bin/env python3

from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.script import Script

s = Script(dbuser='cdb')

core: CoreBackend = s.make_backend("core", proxy=False)
cde: CdEBackend = s.make_backend("cde", proxy=False)

if s.persona_id < 0:
    raise RuntimeError("Need persona id to create changelog entries.")

msg = "Migration von Lastschrift-Beträgen."

with s:
    # Add new columns.
    query = """
        ALTER TABLE core.personas ADD COLUMN donation NUMERIC(8, 2) DEFAULT NULL;
        ALTER TABLE core.changelog ADD COLUMN donation NUMERIC(8, 2);
        ALTER TABLE cde.lastschrift ADD COLUMN revision integer NOT NULL DEFAULT 2;
    """
    core.query_exec(s.rs(), query, ())
    print("Added new columns.")

    # SELECT lastschrift amounts and insert them properly into personas and changelog.
    query = """UPDATE cde.lastschrift SET revision = 1;"""
    num = core.query_exec(s.rs(), query, ())
    step = (num // 10) if num > 20 else 1
    print(f"Set {num} revision counters to 1 for existing lastschrifts.")

    query = """
        SELECT persona_id, amount FROM cde.lastschrift WHERE revoked_at IS NULL;
    """
    print("Updating personas with legacy lastschrifts", end="", flush=True)
    for i, e in enumerate(core.query_all(s.rs(), query, ())):
        data = {
            'id': e['persona_id'],
            'donation': e['amount'] - cde.annual_membership_fee(s.rs()),
        }
        core.set_persona(s.rs(), data, change_note=msg, automated_change=True)

        if i % step == 0:
            print(".", end="", flush=True)
    print()

    # Fix donation values for all personas without a legacy donation.
    query = """
        SELECT id, is_archived FROM core.personas WHERE is_cde_realm = TRUE AND donation IS NULL;
    """
    no_donation_data = core.query_all(s.rs(), query, ())
    num = len(no_donation_data)
    step = (num // 10) if num > 20 else 1
    print(f"Updating {num} personas without lastschrifts", end="", flush=True)

    for i, e in enumerate(no_donation_data):
        if e['is_archived']:
            # Circumvent changelog facility for archived users.
            query = """
                UPDATE core.personas SET donation = 0 WHERE id = %s;
                UPDATE core.changelog SET donation = 0 WHERE persona_id = %s;
            """
            params = (e['id'], e['id'])
            core.query_exec(s.rs(), query, params)
        else:
            # Create changelog entries for non-archived users.
            data = {
                'id': e['id'],
                'donation': 0,
            }
            core.set_persona(s.rs(), data, change_note=msg, automated_change=True)

        if i % step == 0:
            print(".", end="", flush=True)
    print()

    # Add the personas constraint and delete the old column.
    query = """
        ALTER TABLE core.personas ADD CONSTRAINT personas_cde_donation CHECK(NOT is_cde_realm OR donation IS NOT NULL OR is_purged);
        ALTER TABLE cde.lastschrift DROP COLUMN amount;
    """
    core.query_exec(s.rs(), query, ())
    print("Added constraint and deleted old column.")
