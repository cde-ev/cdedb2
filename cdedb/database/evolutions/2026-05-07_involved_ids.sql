BEGIN;
    ALTER TABLE complaint.companions DROP COLUMN involved_persona_id;
COMMIT;
