BEGIN;
    -- Prepare readonly entries and add check constraint.
    UPDATE event.questionnaire_rows SET readonly = NULL WHERE field_id IS NULL;
    UPDATE event.questionnaire_rows SET readonly = false WHERE field_id IS NOT NULL AND readonly IS NULL;
    ALTER TABLE event.questionnaire_rows ADD CONSTRAINT
        questionnaire_row_readonly_field CHECK ((field_id IS NULL) = (readonly IS NULL));
COMMIT;
