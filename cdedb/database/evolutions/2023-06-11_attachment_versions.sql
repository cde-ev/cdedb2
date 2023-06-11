BEGIN;
    REVOKE UPDATE ON assembly.attachment_versions FROM cdb_member;
    GRANT UPDATE (title, authors, filename, dtime) TO cdb_member;
END;
