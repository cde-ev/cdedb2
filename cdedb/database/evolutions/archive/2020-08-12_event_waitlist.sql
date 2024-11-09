BEGIN;
    ALTER TABLE event.event_parts ADD COLUMN waitlist_field integer DEFAULT NULL;
    ALTER TABLE event.event_parts ADD FOREIGN KEY (waitlist_field) REFERENCES event.field_definitions(id);
COMMIT;
