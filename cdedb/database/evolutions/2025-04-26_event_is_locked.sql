BEGIN;
    ALTER TABLE event.events RENAME COLUMN offline_locked TO is_locked;
COMMIT;
