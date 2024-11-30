BEGIN;
    CREATE TABLE event.checkin_periods (
        id                      bigserial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id) ON DELETE CASCADE,
        checkin_time            timestamp(0) WITH TIME ZONE NOT NULL,
        checkout_time           timestamp(0) WITH TIME ZONE DEFAULT NULL,
        UNIQUE (registration_id, checkin_time),
        UNIQUE (registration_id, checkout_time),
        CONSTRAINT checkin_period_time_order CHECK (checkin_time < checkout_time)
    );
    CREATE INDEX checkin_periods_registration_id_idx ON event.checkin_periods(registration_id);
    GRANT SELECT, INSERT, DELETE, UPDATE ON event.checkin_periods TO cdb_persona;
    GRANT SELECT, UPDATE ON event.checkin_periods_id_seq TO cdb_persona;
    INSERT INTO event.checkin_periods (registration_id, checkin_time)
        SELECT id, checkin
        FROM event.registrations
        WHERE checkin IS NOT NULL;
    ALTER TABLE event.registrations DROP COLUMN checkin;
COMMIT;
