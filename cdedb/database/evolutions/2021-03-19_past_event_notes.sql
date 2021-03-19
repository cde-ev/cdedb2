-- Changes column name to be more accurate and easier to handle
ALTER TABLE past_event.events RENAME COLUMN notes TO partcipant_info;
