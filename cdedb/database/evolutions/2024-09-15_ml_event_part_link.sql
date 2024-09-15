BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN event_part_id integer DEFAULT NULL REFERENCES event.event_parts(id);
    ALTER TABLE ml.mailinglists ADD COLUMN event_part_group_id integer DEFAULT NULL REFERENCES event.part_groups(id);
    ALTER TABLE ml.mailinglists ADD CONSTRAINT mailinglists_no_event_specific_without_event
            CHECK (event_id IS NOT NULL OR (event_part_id IS NULL AND event_part_group_id IS NULL));
    ALTER TABLE ml.mailinglists ADD CONSTRAINT mailinglists_no_double_event_specific
            CHECK (event_part_id IS NULL OR event_part_group_id IS NULL);
COMMIT;
