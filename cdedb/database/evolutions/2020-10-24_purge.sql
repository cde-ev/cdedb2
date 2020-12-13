BEGIN;
    ALTER TABLE core.personas ADD COLUMN is_purged boolean NOT NULL DEFAULT FALSE;
    GRANT SELECT (is_purged) ON core.personas TO cdb_anonymous;
    ALTER TABLE core.changelog ADD COLUMN is_purged boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.changelog ALTER COLUMN is_purged DROP DEFAULT;
COMMIT;
