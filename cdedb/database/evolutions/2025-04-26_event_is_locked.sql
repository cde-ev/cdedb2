BEGIN;
    ALTER TABLE event.events RENAME COLUMN offline_lock TO is_locked;
COMMIT;
