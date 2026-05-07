BEGIN;
    ALTER TABLE complaint.companions DROP COLUMN involved_persona_id;
    ALTER TABLE complaint.involved ALTER COLUMN persona_id DROP NOT NULL;
COMMIT;
