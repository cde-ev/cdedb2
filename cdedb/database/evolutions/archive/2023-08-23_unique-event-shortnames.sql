BEGIN;
    ALTER TABLE event.events ADD UNIQUE (shortname);
COMMIT;
