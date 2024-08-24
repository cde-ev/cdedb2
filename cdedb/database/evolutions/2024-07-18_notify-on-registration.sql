BEGIN;
    ALTER TABLE event.events ADD COLUMN notify_on_registration integer NOT NULL DEFAULT 0;
COMMIT;
