BEGIN;
    ALTER TABLE core.personas ADD CONSTRAINT personas_birthday
        CHECK(NOT is_event_realm OR birthday is NOT NULL);
COMMIT;
