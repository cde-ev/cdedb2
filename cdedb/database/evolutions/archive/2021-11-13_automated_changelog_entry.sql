BEGIN;
    ALTER TABLE core.changelog ADD COLUMN automated_change boolean NOT NULL DEFAULT FALSE;
COMMIT;
