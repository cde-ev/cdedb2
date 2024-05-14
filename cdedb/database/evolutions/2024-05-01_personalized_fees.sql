BEGIN;
    CREATE TABLE event.personalized_fees (
            id                      bigserial PRIMARY KEY,
            fee_id                  integer NOT NULL REFERENCES event.event_fees(id) ON DELETE CASCADE,
            registration_id         integer NOT NULL REFERENCES event.registrations(id),
            amount                  numeric(8, 2) NOT NULL
    );
    CREATE INDEX personalized_fees_registration_id_fee_id_idx ON event.personalized_fees(registration_id, fee_id);
    CREATE INDEX personalized_fees_fee_id_idx ON event.personalized_fees(fee_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.personalized_fees TO cdb_persona;
    GRANT SELECT, UPDATE ON event.personalized_fees_id_seq TO cdb_persona;

    ALTER TABLE event.event_fees ALTER COLUMN amount DROP NOT NULL;
    ALTER TABLE event.event_fees ALTER COLUMN condition DROP NOT NULL;
    ALTER TABLE event.event_fees ADD CONSTRAINT event_fee_amount_condition CHECK ((amount IS NULL) = (condition IS NULL));
COMMIT;
