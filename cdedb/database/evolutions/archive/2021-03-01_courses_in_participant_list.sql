-- Changes column name to be more accurate and easier to handle
ALTER TABLE event.events RENAME COLUMN courses_in_participant_list TO is_course_assignment_visible;
