ALTER TABLE core.personas ADD CONSTRAINT personas_trial_member_implicits CHECK (NOT trial_member OR is_member);
