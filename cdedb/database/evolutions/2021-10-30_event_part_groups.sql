BEGIN;
    CREATE TABLE event.part_groups (
            id                      serial PRIMARY KEY,
            event_id                integer REFERENCES event.events(id),
            title                   varchar,
            shortname               varchar,
            notes                   varchar,
            constraint_type         integer NOT NULL
    );
    CREATE INDEX idx_event_part_groups_event_id ON event.event_part_groups(event_id);
    GRANT INSERT, SELECT, UPDATE, DELETE ON event.part_groups TO cdb_persona;
    GRANT SELECT, UPDATE ON event.part_groups_id_seq TO cdb_persona;
    GRANT SELECT ON event.event_part_groups TO cdb_anonymous;

    CREATE TABLE event.part_group_parts (
            id                      serial PRIMARY KEY,
            part_group_id           integer REFERENCES event.part_groups(id),
            part_id                 integer REFERENCES event.event_parts(id)
    );
    CREATE UNIQUE INDEX idx_part_group_parts_constraint ON event.part_group_parts(part_group_id, part_id);
    GRANT INSERT, SELECT, UPDATE, DELETE ON event.part_group_parts TO cdb_persona;
    GRANT SELECT, UPDATE ON event.part_group_parts TO cdb_persona;
    GRANT SELECT ON event.part_group_parts TO cdb_anonymous;
COMMIT;
