BEGIN;
    ALTER TABLE core.genesis_cases ADD COLUMN persona_id integer REFERENCES core.personas(id) DEFAULT NULL;
END;
