BEGIN;
    ALTER TABLE event.events ADD COLUMN participant_notes varchar;
COMMIT;
