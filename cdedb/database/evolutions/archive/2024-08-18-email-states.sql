BEGIN;
    CREATE TABLE  core.email_states (
            id                      serial PRIMARY KEY,
            address                 varchar NOT NULL UNIQUE,
            -- see cdedb.database.constants.EmailStatus
            status                  integer NOT NULL,
            notes                   varchar
    );
    GRANT SELECT on core.email_states TO cdb_anonymous;
    GRANT SELECT, UPDATE ON core.email_states_id_seq TO cdb_admin;
    GRANT INSERT, UPDATE, DELETE ON core.email_states TO cdb_admin;
COMMIT;
