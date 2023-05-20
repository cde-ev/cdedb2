BEGIN;
    UPDATE core.personas SET trial_member = FALSE WHERE is_member = FALSE;
    ALTER TABLE core.personas ADD CONSTRAINT personas_trial_member_implicits CHECK (NOT trial_member OR is_member);
COMMIT;
