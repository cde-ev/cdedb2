BEGIN;
    CREATE TABLE event.checkin_helpers (
        id                      serial PRIMARY KEY,
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        event_id                integer NOT NULL REFERENCES event.events(id),
        UNIQUE (persona_id, event_id)
    );
    CREATE INDEX checkin_helpers_id_idx ON event.checkin_helpers(event_id);
    GRANT INSERT, DELETE ON event.checkin_helpers TO cdb_persona;
    GRANT SELECT, UPDATE ON event.checkin_helpers_id_seq TO cdb_persona;
    GRANT SELECT ON event.checkin_helpers TO cdb_anonymous, cdb_ldap;
COMMIT;
