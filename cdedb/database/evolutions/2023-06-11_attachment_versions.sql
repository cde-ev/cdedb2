BEGIN;
    REVOKE UPDATE ON assembly.attachment_versions FROM cdb_member;
    GRANT UPDATE (title, authors, filename, dtime) ON assembly.attachment_versions TO cdb_member;
END;
