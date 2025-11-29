BEGIN;
    REVOKE INSERT, UPDATE, DELETE ON event.orgas FROM cdb_admin;
    GRANT INSERT, DELETE ON event.orgas TO cdb_persona;
    GRANT SELECT, UPDATE ON event.orgas_id_seq TO cdb_persona;
    CREATE TABLE event.caretakers (
            id                      serial PRIMARY KEY,
            persona_id              integer NOT NULL REFERENCES core.personas(id),
            event_id                integer NOT NULL REFERENCES event.events(id),
            UNIQUE (persona_id, event_id)
    );
    CREATE INDEX caretakers_event_id_idx ON event.caretakers(event_id);
    GRANT INSERT, DELETE ON event.caretakers TO cdb_admin;
    GRANT SELECT, UPDATE ON event.caretakers_id_seq TO cdb_admin;
    GRANT SELECT ON event.caretakers TO cdb_anonymous, cdb_ldap;
COMMIT;
