BEGIN;
    CREATE TABLE event.part_groups (
            id                      serial PRIMARY KEY,
            event_id                integer REFERENCES event.events(id) NOT NULL,
            title                   varchar NOT NULL,
            shortname               varchar NOT NULL,
            notes                   varchar,
            constraint_type         integer NOT NULL,
            UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE,
            UNIQUE (event_id, title) DEFERRABLE INITIALLY IMMEDIATE
    );
    GRANT INSERT, SELECT, DELETE ON event.part_groups TO cdb_persona;
    GRANT UPDATE (title, shortname, notes) ON event.part_groups TO cdb_persona;
    GRANT SELECT, UPDATE ON event.part_groups_id_seq TO cdb_persona;
    GRANT SELECT ON event.part_groups TO cdb_anonymous;

    CREATE TABLE event.part_group_parts (
            id                      serial PRIMARY KEY,
            part_group_id           integer REFERENCES event.part_groups(id),
            part_id                 integer REFERENCES event.event_parts(id),
            UNIQUE (part_id, part_group_id) DEFERRABLE INITIALLY IMMEDIATE
    );
    GRANT INSERT, SELECT, DELETE ON event.part_group_parts TO cdb_persona;
    GRANT SELECT, UPDATE ON event.part_group_parts_id_seq TO cdb_persona;
    GRANT SELECT ON event.part_group_parts TO cdb_anonymous;
COMMIT;
