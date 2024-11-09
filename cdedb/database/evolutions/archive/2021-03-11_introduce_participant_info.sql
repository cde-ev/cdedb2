BEGIN;
    ALTER TABLE event.events ADD COLUMN participant_info varchar;
COMMIT;
