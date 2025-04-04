BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN event_part_group_id integer DEFAULT NULL REFERENCES event.part_groups(id);
    ALTER TABLE ml.mailinglists ADD CONSTRAINT mailinglists_no_event_specific_without_event
            CHECK (event_id IS NOT NULL OR event_part_group_id IS NULL);
COMMIT;
