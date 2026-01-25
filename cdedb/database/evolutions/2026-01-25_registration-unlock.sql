BEGIN;
    ALTER TABLE event.events ADD COLUMN registration_unlocked boolean NOT NULL DEFAULT FALSE;
    UPDATE event.events SET registration_unlocked = TRUE;
COMMIT;
