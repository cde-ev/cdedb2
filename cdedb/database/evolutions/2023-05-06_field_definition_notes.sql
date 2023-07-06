BEGIN;
    ALTER TABLE event.events ADD COLUMN field_definition_notes varchar;
COMMIT;
