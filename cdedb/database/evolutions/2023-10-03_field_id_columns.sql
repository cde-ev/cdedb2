BEGIN;
    ALTER TABLE event.events RENAME COLUMN lodge_field TO lodge_field_id;
    ALTER TABLE event.event_parts RENAME COLUMN waitlist_field TO waitlist_field_id;
    ALTER TABLE event.event_parts RENAME COLUMN camping_mat_field TO camping_mat_field_id;
    ALTER TABLE event.course_tracks RENAME COLUMN course_room_field TO course_room_field_id;
COMMIT;
