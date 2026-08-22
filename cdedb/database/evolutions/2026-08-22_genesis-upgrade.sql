BEGIN;
    ALTER TABLE core.genesis_cases ADD COLUMN is_upgrade boolean NOT NULL DEFAULT FALSE;
COMMIT;
