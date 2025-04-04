BEGIN;
    ALTER TABLE event.field_definitions ADD COLUMN description varchar;
    ALTER TABLE event.field_definitions ADD COLUMN sort_group varchar;
COMMIT;
