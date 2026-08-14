BEGIN;
    ALTER TABLE complaint.companions DROP COLUMN involved_persona_id;
    ALTER TABLE complaint.involved ALTER COLUMN persona_id DROP NOT NULL;
    ALTER TABLE complaint.involved RENAME COLUMN involved_type TO involvement_type;
    GRANT UPDATE (persona_id, involvement_type, is_informed) ON complaint.involved TO cdb_admin;
COMMIT;
