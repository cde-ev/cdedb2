BEGIN;
    CREATE TABLE event.personalized_fees (
            id                      bigserial PRIMARY KEY,
            fee_id                  integer NOT NULL REFERENCES event.event_fees(id) ON DELETE CASCADE,
            registration_id         integer NOT NULL REFERENCES event.registrations(id) ON DELETE CASCADE,
            UNIQUE (fee_id, registration_id),
            amount                  numeric(8, 2) NOT NULL
    );
    CREATE INDEX personalized_fees_registration_id_idx ON event.personalized_fees(registration_id);
    GRANT SELECT, INSERT, UPDATE, DELETE ON event.personalized_fees TO cdb_persona;
    GRANT SELECT, UPDATE ON event.personalized_fees_id_seq TO cdb_persona;
    GRANT SELECT ON event.personalized_fees_id_seq TO cdb_anonymous;

    ALTER TABLE event.event_fees ALTER COLUMN amount DROP NOT NULL;
    ALTER TABLE event.event_fees ALTER COLUMN condition DROP NOT NULL;
    ALTER TABLE event.event_fees ADD CONSTRAINT event_fee_amount_condition CHECK ((amount IS NULL) = (condition IS NULL));
COMMIT;
