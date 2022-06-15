BEGIN;
    ALTER TABLE event.events ADD COLUMN event_keeper_log_id integer NOT NULL DEFAULT 0;
COMMIT;
