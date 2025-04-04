BEGIN;
    CREATE TABLE event.helpers (
            id                      serial PRIMARY KEY,
            persona_id              integer UNIQUE NOT NULL REFERENCES core.personas(id)
    );
    GRANT INSERT, UPDATE, DELETE ON event.helpers TO cdb_admin;
    GRANT SELECT, UPDATE ON event.helpers_id_seq TO cdb_admin;
    GRANT SELECT ON event.helpers TO cdb_anonymous, cdb_ldap;
COMMIT;
