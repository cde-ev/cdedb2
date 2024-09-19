BEGIN;
    ALTER TABLE event.event_parts ADD COLUMN camping_mat_field integer DEFAULT NULL REFERENCES event.field_definitions(id);
    ALTER TABLE event.course_tracks ADD COLUMN course_room_field integer DEFAULT NULL REFERENCES event.field_definitions(id);
    UPDATE event.event_parts SET camping_mat_field = e.camping_mat_field
        FROM event.events AS e WHERE event_id = e.id;
    UPDATE event.course_tracks SET course_room_field = e.course_room_field
        FROM event.events AS e, event.event_parts AS ep
        WHERE part_id = ep.id AND ep.event_id = e.id;
    ALTER TABLE event.events DROP COLUMN camping_mat_field;
    ALTER TABLE event.events DROP COLUMN course_room_field;
COMMIT;
