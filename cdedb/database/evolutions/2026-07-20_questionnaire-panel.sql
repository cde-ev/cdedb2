BEGIN;
    ALTER TABLE event.questionnaire_text_rows ADD COLUMN panel_kind integer;
COMMIT;
