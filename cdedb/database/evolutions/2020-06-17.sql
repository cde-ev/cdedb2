-- This evolutions represents the changes made as part of the PR #1147.
-- This creates a new table for assembly attachments to allow tracking different versions of the same file.

-- #####################################################################################################################
-- WARNING! This represents ONLY! the schema changes. All old attachment metadata will be lost when executing this.    #
-- For live migration or migration of any (local) instance with attachment data present use the associated migration   #
-- script `bin/migrate_attachments_to_versioning` instead. The script will also take care of renaming the actual files.#
-- #####################################################################################################################
-- You have been warned!#
-- ######################

CREATE TABLE assembly.attachment_versions (
    id              bigserial PRIMARY KEY,
    attachment_id   integer references assembly.attachments(id),
    version         integer NOT NULL DEFAULT 1,
    title           varchar,
    authors         varchar,
    filename        varchar,
    ctime           timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
    dtime           timestamp WITH TIME ZONE DEFAULT NULL,
    file_hash       varchar NOT NULL
);
CREATE INDEX idx_attachment_versions_attachment_id ON assembly.attachment_versions(attachment_id);
CREATE UNIQUE INDEX idx_attachment_version_constraint ON assembly.attachment_versions(attachment_id, version);
GRANT SELECT ON assembly.attachment_versions TO cdb_member;
GRANT INSERT, DELETE, UPDATE on assembly.attachment_versions TO cdb_admin;
GRANT SELECT, UPDATE on assembly.attachment_versions_id_seq TO cdb_admin;

GRANT UPDATE ON assembly.attachments TO cdb_admin;

-- This is the part were information will be deleted, that you were warned about.
ALTER TABLE assembly.attachments DROP COLUMN title, DROP COLUMN filename;