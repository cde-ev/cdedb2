-- This evolution is just for a proof of concept for compiling database descriptions.
-- It causes the database comparison to show an error, since this change is not
-- included in the `cdedb-tables.sql` file.
BEGIN;
    ALTER TABLE core.personas ADD COLUMN more_notes VARCHAR;
    GRANT SELECT (more_notes) ON core.personas TO cdb_anonymous;
COMMIT;