BEGIN;
    ALTER TABLE event.events ADD COLUMN website_url varchar;
COMMIT;
