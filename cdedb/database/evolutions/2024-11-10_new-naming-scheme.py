#!/usr/bin/env python3
from cdedb.backend.core import CoreBackend
from cdedb.script import Script

persona_id = -1
s = Script(persona_id=persona_id, dbuser='cdb')

core: CoreBackend = s.make_backend("core", proxy=False)

with s:
    # add new columns with default null
    q = """
        ALTER TABLE core.personas ADD COLUMN nickname VARCHAR;
        ALTER TABLE core.personas ADD COLUMN legal_given_names VARCHAR;
        GRANT UPDATE (nickname, legal_given_names) ON core.personas TO cdb_persona;
        ALTER TABLE core.changelog ADD COLUMN nickname VARCHAR;
        ALTER TABLE core.changelog ADD COLUMN legal_given_names VARCHAR;
    """
    core.query_exec(s.rs(), q, ())

    # migrate all entries of the changelog and core.personas with basic logic
    #  display_name -> nickname, given_names -> legal_given_names
    q = """
            UPDATE core.changelog SET legal_given_names = given_names;
            UPDATE core.changelog SET nickname = display_name WHERE display_name != given_names;
            UPDATE core.personas SET legal_given_names = given_names;
            UPDATE core.personas SET nickname = display_name WHERE display_name != given_names;
    """
    core.query_exec(s.rs(), q, ())

    # drop display_name column, make legal_given_names not null
    q = """
        ALTER TABLE core.personas DROP COLUMN display_name VARCHAR;
        ALTER TABLE core.personas ALTER COLUMN legal_given_names SET NOT NULL;
        ALTER TABLE core.changelog DROP COLUMN display_name VARCHAR;
    """
    core.query_exec(s.rs(), q, ())

    # add new generation for non-archived users with enhanced logic
    q = """
        SELECT id, nickname, given_names FROM core.personas WHERE is_archived = FALSE AND nickname IS NOT NULL;
    """
    change_note = "Namenssemantik geändert."
    data = core.query_all(s.rs(), q, ())
    review_forced = 0
    for persona in data:
        force_review = False
        if persona["nickname"].lower() not in persona["given_names"].lower():
            force_review = True
            review_forced += 1
        persona["given_names"] = persona["nickname"]
        persona["nickname"] = None
        core.set_persona(s.rs(), persona, change_note=change_note, force_review=force_review, automated_change=True)

    print(f"Migrated {len(data)} personas with enhanced logic.")
    print(f"Processed {len(data) - review_forced} personas automatically, forced manual review for {review_forced} personas.")
