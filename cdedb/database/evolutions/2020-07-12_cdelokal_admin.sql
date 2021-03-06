BEGIN;
    ALTER TABLE core.personas ADD COLUMN is_cdelokal_admin boolean NOT NULL DEFAULT FALSE;
    GRANT SELECT is_cdelokal_admin ON core.personas TO cdb_anonymous;
    ALTER TABLE core.changelog ADD COLUMN is_cdelokal_admin boolean DEFAULT FALSE;
    ALTER TABLE core.changelog ALTER COLUMN is_cdelokal_admin DROP DEFAULT;
    ALTER TABLE core.privilege_changes ADD COLUMN is_cdelokal_admin boolean DEFAULT NULL;
COMMIT;
