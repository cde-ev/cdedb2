BEGIN;
    -- Add title column.
    ALTER TABLE event.field_definitions ADD COLUMN title varchar;
    UPDATE event.field_definitions SET title = field_name;
    ALTER TABLE event.field_definitions ALTER COLUMN title SET NOT NULL;
    ALTER TABLE event.field_definitions ADD COLUMN sortkey integer NOT NULL DEFAULT 0;
COMMIT;
