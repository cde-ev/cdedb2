BEGIN;
    CREATE TABLE event.orga_apitokens (
        id          serial PRIMARY KEY,
        event_id    integer NOT NULL REFERENCES event.events(id),
        secret_hash varchar,
        ctime       timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        etime       timestamp WITH TIME ZONE NOT NULL,
        rtime       timestamp WITH TIME ZONE,
        atime       timestamp WITH TIME ZONE,
        title       varchar NOT NULL,
        notes       varchar
    );
    CREATE INDEX orga_apitokens_event_id_idx ON event.orga_apitokens(event_id);
    GRANT SELECT ON event.orga_apitokens TO cdb_anonymous;
    GRANT UPDATE (atime) ON event.orga_apitokens TO cdb_anonymous;
    GRANT SELECT, INSERT, DELETE ON event.orga_apitokens TO cdb_persona;
    GRANT UPDATE (secret_hash, rtime, title, notes) ON event.orga_apitokens TO cdb_persona;
    GRANT SELECT, UPDATE ON event.orga_apitokens_id_seq TO cdb_persona;

    ALTER TABLE event.log ADD COLUMN droid_id integer REFERENCES event.orga_apitokens(id);
    ALTER TABLE event.log ADD CONSTRAINT event_log_submitted_by_droid CHECK (submitted_by is NULL or droid_id is NULL);
COMMIT;
