BEGIN;
    ALTER TABLE event.event_parts ADD UNIQUE (event_id, shortname) DEFERRABLE INITIALLY IMMEDIATE;
    CREATE TABLE event.event_fees (
        id                           serial PRIMARY KEY,
        event_id                     integer NOT NULL REFERENCES event.events (id),
        title                        varchar NOT NULL,
        amount                       numeric(8, 2) NOT NULL,
        condition                    varchar NOT NULL,
        notes                        varchar
    );
    GRANT INSERT, SELECT, UPDATE, DELETE ON event.event_fees TO cdb_persona;
    GRANT SELECT, UPDATE on event.event_fees_id_seq TO cdb_persona;
    GRANT SELECT on event.event_fees TO cdb_anonymous;

    INSERT INTO event.event_fees(event_id, title, amount, condition)
    SELECT event_id, shortname AS title, fee AS amount, 'part.' || shortname AS condition FROM event.event_parts;

    ALTER TABLE event.event_parts DROP COLUMN fee;

    INSERT INTO event.event_fees(event_id, title, amount, condition)
    SELECT ep.event_id, modifier_name AS title, amount, 'part.' || shortname || ' and field.' || field_name FROM event.fee_modifiers AS fm JOIN event.event_parts AS ep ON ep.id = fm.part_id JOIN event.field_definitions ON fm.field_id = field_definitions.id;

    DROP TABLE event.fee_modifiers;

    INSERT INTO event.event_fees(event_id, title, amount, condition)
    SELECT id, 'Externenzusatzbeitrag' AS title, non_member_surcharge, 'not is_member' FROM event.events WHERE nonmember_surcharge != 0;

    ALTER TABLE event.events DROP COLUMN nonmember_surcharge;
COMMIT;
