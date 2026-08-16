BEGIN;
    ALTER TABLE event.questionnaire_rows DROP CONSTRAINT questionnaire_row_readonly_field;
    UPDATE event.questionnaire_rows SET readonly = FALSE WHERE field_id IS NULL;
    ALTER TABLE event.questionnaire_rows ALTER COLUMN readonly SET NOT NULL;
COMMIT;
