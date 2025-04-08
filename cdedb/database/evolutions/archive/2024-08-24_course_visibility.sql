BEGIN;
    ALTER TABLE event.courses ADD COLUMN is_visible boolean NOT NULL DEFAULT TRUE;
COMMIT;
