BEGIN;
    ALTER TABLE event.events RENAME COLUMN registration_text TO registration_status_text;
    ALTER TABLE event.events ADD COLUMN questionnaire_notes VARCHAR;
COMMIT;
