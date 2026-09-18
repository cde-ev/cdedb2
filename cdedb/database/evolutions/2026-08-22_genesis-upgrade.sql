BEGIN;
    ALTER TABLE core.genesis_cases ADD COLUMN is_upgrade boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.genesis_cases ADD CONSTRAINT genesis_cases_upgrade_status CHECK ( NOT is_upgrade OR status != 1 );
    ALTER TABLE core.genesis_cases ADD CONSTRAINT genesis_cases_upgrade_persona CHECK ( NOT is_upgrade OR persona_id IS NOT NULL );
COMMIT;
