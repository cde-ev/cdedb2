BEGIN;
    CREATE TABLE event.custom_query_filters (
            id                      bigserial PRIMARY KEY,
            event_id                integer NOT NULL REFERENCES event.events,
            -- See cdedb.common.query.QueryScope:
            scope                   integer NOT NULL,
            fields                  varchar NOT NULL,
            title                   varchar NOT NULL,
            notes                   varchar,
            UNIQUE (event_id, title),
            UNIQUE (event_id, fields)
    );
    GRANT SELECT ON event.custom_query_filters TO cdb_anonymous;
    GRANT INSERT, UPDATE, DELETE ON event.custom_query_filters TO cdb_persona;
    GRANT SELECT, UPDATE ON event.custom_query_filters_id_seq TO cdb_persona;
COMMIT;
