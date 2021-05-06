BEGIN;
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_username
        CHECK ((username IS NULL) = is_archived);
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_member
        CHECK (NOT is_member OR NOT is_archived);
COMMIT;
