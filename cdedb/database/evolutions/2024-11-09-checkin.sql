BEGIN;
    CREATE TABLE event.checkin_transitions (
            id                  serial PRIMARY KEY,
            registration_id     integer NOT NULL REFERENCES event.registrations(id) ON DELETE CASCADE,
            transition_type     integer NOT NULL DEFAULT 1,
            ttime               timestamp WITH TIME ZONE NOT NULL DEFAULT now()
    );
    INSERT INTO event.checkin_transitions (registration_id, checkin)
        SELECT id, checkin
        FROM event.registrations;
    ALTER TABLE event.checkin_transitions ALTER COLUMN transition_type DROP DEFAULT;
    ALTER TABLE event.registrations DROP COLUMN checkin;
COMMIT;
