BEGIN;
    ALTER TABLE assembly.attachment_versions ADD COLUMN changenotes varchar;
    GRANT UPDATE (changenotes) ON assembly.attachment_versions TO cdb_member;
COMMIT;