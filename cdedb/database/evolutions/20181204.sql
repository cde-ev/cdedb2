ALTER TABLE event.course_tracks
    ADD COLUMN shortname varchar,
    ADD COLUMN num_choices integer NOT NULL DEFAULT 3,
    ADD COLUMN sortkey integer NOT NULL DEFAULT 1;

ALTER TABLE event.course_tracks ALTER COLUMN num_choices DROP DEFAULT;
ALTER TABLE event.course_tracks ALTER COLUMN sortkey DROP DEFAULT;
