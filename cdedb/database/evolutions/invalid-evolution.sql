-- This evolution is just for a prrof of concept for compiling database descriptions.
BEGIN;
    ALTER TABLE core.personas ADD COLUMN more_notes VARCHAR;
    GRANT SELECT (more_notes) ON core.personas TO cdb_anonymous;
COMMIT;