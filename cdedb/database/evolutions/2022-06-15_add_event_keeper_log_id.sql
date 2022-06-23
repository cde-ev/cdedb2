BEGIN;
    CREATE TABLE event.keeper (
        id                      serial PRIMARY KEY,
        event_id                integer UNIQUE NOT NULL REFERENCES event.events(id),
        log_id                  integer NOT NULL DEFAULT 0
    );
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.keeper TO cdb_persona;
    GRANT SELECT, UPDATE ON event.keeper_id_seq TO cdb_persona;
    -- TODO: add entries for existing events
COMMIT;
