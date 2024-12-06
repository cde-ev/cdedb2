BEGIN;
    ALTER TABLE core.personas ADD COLUMN show_legal_given_names boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.personas ADD COLUMN searchable_legal_given_names varchar GENERATED ALWAYS AS (
        CASE WHEN show_legal_given_names THEN legal_given_names ELSE NULL END) STORED;
    GRANT UPDATE (show_legal_given_names) ON core.personas TO cdb_persona;
COMMIT;
