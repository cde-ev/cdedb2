BEGIN;
    ALTER TABLE event.event_parts ADD COLUMN camping_mat_field;
    ALTER TABLE event.course_tracks ADD COLUMN course_room_field;
    -- some magic migration
    ALTER TABLE event.events DROP COLUMN camping_mat_field;
    ALTER TABLE event.events DROP COLUMN course_room_field;
COMMIT;
