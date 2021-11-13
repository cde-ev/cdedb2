BEGIN;
    ALTER TABLE core.changelog ADD COLUMN automated_change boolean DEFAULT FALSE;
COMMIT;
