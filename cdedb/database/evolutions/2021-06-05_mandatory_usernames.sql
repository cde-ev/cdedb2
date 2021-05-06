BEGIN;
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_username
        CHECK ((username IS NULL) = is_archived);
COMMIT;
