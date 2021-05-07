BEGIN;
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_username
        CHECK ((username IS NULL) = is_archived);
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_member
        CHECK (NOT (is_member AND is_archived));
COMMIT;
