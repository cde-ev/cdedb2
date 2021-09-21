BEGIN;
    ALTER TABLE core.genesis_cases ADD COLUMN pevent_id integer REFERENCES past_event.events(id) DEFAULT NULL;
COMMIT;
