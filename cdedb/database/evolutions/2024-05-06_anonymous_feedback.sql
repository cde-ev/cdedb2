BEGIN;
    CREATE TABLE core.anonymous_messages (
            id                      serial PRIMARY KEY,
            message_id              varchar NOT NULL UNIQUE,
            recipient               varchar NOT NULL,
            ctime                   timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
            encrypted_data          varchar NOT NULL
    );
    CREATE INDEX anonymous_messages_message_id_idx ON core.anonymous_messages(message_id);
    GRANT SELECT ON core.anonymous_messages TO cdb_admin;
    GRANT SELECT(id), INSERT ON core.anonymous_messages TO cdb_persona;
    GRANT SELECT, UPDATE ON core.anonymous_messages_id_seq TO cdb_persona;
COMMIT;
