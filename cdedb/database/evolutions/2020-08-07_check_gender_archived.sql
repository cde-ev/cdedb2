BEGIN;
    ALTER TABLE core.personas DROP CONSTRAINT personas_check;
    ALTER TABLE core.personas ADD CHECK((NOT is_cde_realm AND NOT is_event_realm) OR is_archived OR gender IS NOT NULL);
COMMIT;
