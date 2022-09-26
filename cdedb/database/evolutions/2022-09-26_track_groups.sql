BEGIN;
    CREATE TABLE event.track_groups (
            id                      serial PRIMARY KEY,
            event_id                integer REFERENCES event.events(id) NOT NULL,
            title                   varchar NOT NULL,
            shortname               varchar NOT NULL,
            notes                   varchar,
            constraint_type         integer NOT NULL,
            sortkey                 integer NOT NULL,
            UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE,
            UNIQUE (event_id, title) DEFERRABLE INITIALLY IMMEDIATE
    );
    GRANT INSERT, SELECT, DELETE ON event.track_groups TO cdb_persona;
    GRANT UPDATE (title, shortname, notes) ON event.track_groups TO cdb_persona;
    GRANT SELECT, UPDATE ON event.track_groups_id_seq TO cdb_persona;
    GRANT SELECT ON event.track_groups TO cdb_anonymous;

    CREATE TABLE event.track_group_tracks (
            id                      serial PRIMARY KEY,
            track_group_id          integer REFERENCES event.track_groups(id) NOT NULL,
            track_id                integer REFERENCES event.course_tracks(id) NOT NULL,
            UNIQUE (track_id, track_group_id) DEFERRABLE INITIALLY IMMEDIATE
    );
    CREATE INDEX track_group_tracks_track_group_id_idx ON event.track_group_tracks(track_group_id);
    GRANT INSERT, SELECT, DELETE ON event.track_group_tracks TO cdb_persona;
    GRANT SELECT, UPDATE ON event.track_group_tracks_id_seq TO cdb_persona;
    GRANT SELECT ON event.track_group_tracks TO cdb_anonymous;
END;
