BEGIN;
    ALTER TABLE event.field_definitions ADD COLUMN checkin boolean NOT NULL DEFAULT FALSE;
COMMIT;
