BEGIN;
    CREATE TABLE event.checkin_periods (
        id                      serial PRIMARY KEY,
        registration_id         integer NOT NULL REFERENCES event.registrations(id) ON DELETE CASCADE,
        checkin_time            timestamp WITH TIME ZONE NOT NULL,
        checkout_time           timestamp WITH TIME ZONE DEFAULT NULL
    );
    CREATE INDEX checkin_periods_registration_id_idx ON event.checkin_periods(registration_id);
    GRANT SELECT, INSERT, DELETE, UPDATE (checkin_time, checkout_time) ON event.checkin_periods TO cdb_persona;
    INSERT INTO event.checkin_periods (registration_id, checkin_time)
        SELECT id, checkin
        FROM event.registrations;
    ALTER TABLE event.registrations DROP COLUMN checkin;
COMMIT;
