BEGIN;
    ALTER TABLE event.events ADD COLUMN is_registration_approved boolean NOT NULL DEFAULT FALSE;
    UPDATE event.events SET is_registration_approved = TRUE;
COMMIT;
