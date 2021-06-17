BEGIN;
    CREATE TABLE event.stored_queries (
            id                      bigserial PRIMARY KEY,
            event_id                integer NOT NULL REFERENCES event.events,
            query_name              varchar NOT NULL,
            scope                   varchar NOT NULL,
            serialized_query        jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT event_unique_query UNIQUE(event_id, query_name)
    );
    CREATE INDEX idx_stored_queries_event_id ON event.stored_queries(event_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.stored_queries TO cdb_persona;
    GRANT SELECT, UPDATE ON event.stored_queries_id_seq TO cdb_persona;
COMMIT;
