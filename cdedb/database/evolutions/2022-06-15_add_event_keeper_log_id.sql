BEGIN;
    CREATE TABLE event.keeper;
    ALTER TABLE event.keeper ADD COLUMN event_id integer UNIQUE REFERENCES event.events(id);
    ALTER TABLE event.keeper ADD COLUMN log_id integer NOT NULL DEFAULT 0;
    -- TODO: add entries for existing events
COMMIT;
