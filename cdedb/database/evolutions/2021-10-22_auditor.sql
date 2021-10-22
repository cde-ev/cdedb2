BEGIN;
    ALTER TABLE core.personas ADD COLUMN is_auditor boolean NOT NULL DEFAULT FALSE;
    GRANT SELECT is_auditor ON core.personas TO cdb_anonymous;
    ALTER TABLE core.personas ADD CONSTRAINT personas_auditor CHECK (NOT is_auditor OR is_cde_realm);
    ALTER TABLE core.changelog ADD COLUMN is_auditor boolean DEFAULT FALSE;
    ALTER TABLE core.changelog ALTER COLUMN is_auditor DROP DEFAULT;
    ALTER TABLE core.privilege_changes ADD COLUMN is_auditor boolean DEFAULT NULL;
COMMIT;
