BEGIN;
    ALTER TABLE core.gensis_cases ADD COLUMN pevent_id integer REFERENCES past_event.events(id) DEFAULT NULL;
COMMIT;
