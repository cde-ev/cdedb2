BEGIN;
    ALTER TABLE complaint.entry_versions ALTER COLUMN timestamp DROP NOT NULL;
    ALTER TABLE complaint.entry_versions DROP CONSTRAINT complaint_entry_deletion_reason;
    ALTER TABLE complaint.entry_versions DROP CONSTRAINT complaint_entry_deletion_by;
    ALTER TABLE complaint.entry_versions ADD COLUMN marked_for_purge timestamp WITH TIME ZONE DEFAULT NULL;
    ALTER TABLE complaint.entry_versions ADD COLUMN purged_by integer REFERENCES core.personas(id);
    ALTER TABLE complaint.entry_versions ADD COLUMN is_purged boolean NOT NULL DEFAULT False;
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_deletion_reason
            CHECK ((dtime IS NULL) = (dreason IS NULL) OR is_purged);
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_deletion_by
            CHECK ((dtime IS NULL) = (deleted_by IS NULL) OR is_purged);
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_version_marked_for_purge_by
            CHECK ((marked_for_purge IS NULL) = (purged_by IS NULL));
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_purged
            CHECK (
                is_purged = (timestamp IS NULL)
                AND NOT is_purged OR (description IS NULL)
                AND NOT is_purged OR (length IS NULL)
                AND NOT is_purged OR (dreason IS NULL)
                AND NOT is_purged OR (attachment_hash IS NULL)
                AND NOT is_purged OR (attachment_title IS NULL)
                AND NOT is_purged OR (attachment_filename IS NULL)
            );

    REVOKE UPDATE, INSERT ON complaint.entry_versions FROM cdb_persona;
    REVOKE UPDATE ON complaint.entry_versions_id_seq FROM cdb_persona;
    GRANT INSERT, UPDATE (dtime, dreason, deleted_by, marked_for_purge, purged_by) ON complaint.entry_versions TO cdb_admin;
    GRANT UPDATE (is_purged, description, length, timestamp, dreason, attachment_hash, attachment_title, attachment_filename) ON complaint.entry_versions TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.entry_versions_id_seq TO cdb_admin;

    REVOKE INSERT ON complaint.authors FROM cdb_persona;
    REVOKE SELECT, UPDATE ON complaint.authors_id_seq FROM cdb_persona;
    GRANT INSERT ON complaint.authors TO cdb_admin;
    GRANT DELETE ON complaint.authors TO cdb_admin;
COMMIT;
