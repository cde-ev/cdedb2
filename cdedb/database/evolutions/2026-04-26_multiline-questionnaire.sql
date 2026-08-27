BEGIN;
    UPDATE event.field_definitions fd SET kind = 50 WHERE kind = 1 AND EXISTS (
        SELECT * FROM event.questionnaire_rows WHERE field_id = fd.id AND input_size > 0
    );
    ALTER TABLE event.questionnaire_rows DROP COLUMN input_size;
COMMIT;
