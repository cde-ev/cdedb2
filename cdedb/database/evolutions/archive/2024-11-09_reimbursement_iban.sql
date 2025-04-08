BEGIN;
    ALTER TABLE event.events ADD COLUMN reimbursement_iban_field_id integer DEFAULT NULL REFERENCES event.field_definitions(id);
COMMIT;
