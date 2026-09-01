BEGIN;
    ALTER TABLE complaint.entry_versions ADD COLUMN attachment_hash varchar DEFAULT NULL;
    ALTER TABLE complaint.entry_versions ADD COLUMN attachment_title varchar DEFAULT NULL;
    ALTER TABLE complaint.entry_versions ADD COLUMN attachment_filename varchar DEFAULT NULL;
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_attachment_title
        CHECK ((attachment_hash IS NULL) = (attachment_title IS NULL));
    ALTER TABLE complaint.entry_versions ADD CONSTRAINT complaint_entry_attachment_filename
        CHECK ((attachment_hash IS NULL) = (attachment_filename IS NULL));
    CREATE INDEX entry_versions_attachment_hash ON complaint.entry_versions(attachment_hash);
COMMIT;
