BEGIN;
    ALTER TABLE event.stored_queries ADD COLUMN query_group VARCHAR;
COMMIT;
