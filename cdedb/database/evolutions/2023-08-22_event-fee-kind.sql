BEGIN;
    ALTER TABLE event.event_fees ADD COLUMN kind integer NOT NULL DEFAULT 1;
    -- ALTER TABLE event.event_fees ALTER COLUMN kind DROP DEFAULT;
COMMIT;
