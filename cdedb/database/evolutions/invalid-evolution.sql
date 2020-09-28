BEGIN;
    ALTER TABLE core.personas ADD COLUMN more_notes VARCHAR;
COMMIT;