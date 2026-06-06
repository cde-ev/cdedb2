BEGIN;
    ALTER TABLE core.personas ADD COLUMN is_complaint_admin boolean NOT NULL DEFAULT False;
    ALTER TABLE core.personas ADD CONSTRAINT personas_complaint_admin_event_realm
        CHECK (NOT is_complaint_admin OR is_event_realm);
    GRANT SELECT (is_complaint_admin) ON core.personas TO cdb_anonymous, cdb_ldap;

    ALTER TABLE core.privilege_changes ADD COLUMN is_complaint_admin boolean DEFAULT NULL;

    ALTER TABLE core.changelog ADD COLUMN is_complaint_admin boolean;

    CREATE SCHEMA complaint;
    GRANT USAGE ON SCHEMA complaint TO cdb_persona;

    CREATE TABLE complaint.cases (
        id         serial PRIMARY KEY,
        kind       integer NOT NULL, -- database.constants.ComplaintKind
        is_grave   boolean DEFAULT FALSE,
        summary    varchar NOT NULL,
        start_date date,
        end_date   date
    );
    GRANT SELECT ON complaint.cases TO cdb_persona;
    GRANT INSERT, UPDATE, DELETE ON complaint.cases TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.cases_id_seq TO cdb_admin;

    CREATE TABLE complaint.access_log (
        id              bigserial PRIMARY KEY,
        persona_id      integer NOT NULL REFERENCES core.personas(id),
        case_id         integer NOT NULL REFERENCES complaint.cases(id),
        ctime           timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        atime           timestamp WITH TIME ZONE NOT NULL DEFAULT now(),
        UNIQUE (persona_id, case_id)
    );
    GRANT SELECT, INSERT, UPDATE(ctime, atime), DELETE ON complaint.access_log TO cdb_persona;
    GRANT SELECT, UPDATE ON complaint.access_log_id_seq TO cdb_persona;

    CREATE TABLE complaint.entries (
        id            serial PRIMARY KEY,
        case_id       integer NOT NULL REFERENCES complaint.cases(id),
        entry_type    integer DEFAULT NULL, -- database.constants.ComplaintEntryType
        parent_id     integer REFERENCES complaint.entries(id) DEFAULT NULL, -- only for some types
        concerned_id  integer REFERENCES core.personas(id) DEFAULT NULL,  -- maybe reference involved_id instead
        is_revoked    boolean NOT NULL DEFAULT FALSE
    );
    GRANT SELECT, INSERT, UPDATE (is_revoked) ON complaint.entries TO cdb_persona;
    GRANT SELECT, UPDATE ON complaint.entries_id_seq TO cdb_persona;

    CREATE TABLE complaint.entry_versions (
        id            serial PRIMARY KEY,
        entry_id      integer NOT NULL REFERENCES complaint.entries(id),
        submitted_by  integer NOT NULL REFERENCES core.personas(id),
        description   bytea, -- encrypted
        length        integer,
        CONSTRAINT complaint_entry_empty_description_length
            CHECK ((description IS NULL) = (length IS NULL)),
        ctime         timestamp WITH TIME ZONE NOT NULL DEFAULT NOW(),
        timestamp     timestamp WITH TIME ZONE NOT NULL DEFAULT NOW(),
        etime         timestamp WITH TIME ZONE DEFAULT NULL,
        -- is_shared     boolean NOT NULL DEFAULT TRUE, -- with companions with shared involved personas
        dtime         timestamp WITH TIME ZONE DEFAULT NULL,  -- to be updated on deletion
        dreason       varchar DEFAULT NULL,
        deleted_by    integer REFERENCES core.personas(id) DEFAULT NULL,
        UNIQUE(entry_id, dtime),
        CONSTRAINT complaint_entry_deletion_reason
            CHECK ((dtime IS NULL) = (dreason IS NULL)),
        CONSTRAINT complaint_entry_deletion_by
            CHECK ((dtime IS NULL) = (deleted_by IS NULL))
    );
    CREATE UNIQUE INDEX entry_versions_id_current ON complaint.entry_versions(entry_id) WHERE dtime IS NULL;
    GRANT SELECT, INSERT, UPDATE (dtime, dreason, deleted_by) ON complaint.entry_versions TO cdb_persona;
    GRANT SELECT, UPDATE ON complaint.entry_versions_id_seq TO cdb_persona;

    CREATE TABLE complaint.authors (
        id                      serial PRIMARY KEY,
        entry_version_id        integer NOT NULL REFERENCES complaint.entry_versions(id),
        persona_id              integer NOT NULL REFERENCES core.personas(id),
        UNIQUE(entry_version_id, persona_id)
    );
    GRANT SELECT, INSERT ON complaint.authors TO cdb_persona;
    GRANT SELECT, UPDATE ON complaint.authors_id_seq TO cdb_persona;

    CREATE TABLE complaint.involved (
        id            serial PRIMARY KEY,
        case_id       int NOT NULL REFERENCES complaint.cases(id),
        persona_id    int NOT NULL REFERENCES core.personas(id),
        UNIQUE(case_id, persona_id),
        involved_type integer NOT NULL, -- database.constants.ComplaintInvolvementType
        is_informed   boolean NOT NULL DEFAULT FALSE
    );
    GRANT SELECT ON complaint.involved TO cdb_persona;
    GRANT INSERT, UPDATE (is_informed), DELETE ON complaint.involved TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.involved_id_seq TO cdb_admin;

    -- very limited access per case and persona
    CREATE TABLE complaint.companions (
        id                      serial PRIMARY KEY,
        -- Who is being accompanied in which case.
        case_id                 int NOT NULL REFERENCES complaint.cases(id),
        involved_persona_id     int NOT NULL REFERENCES core.personas(id),
        -- This is duplicating the info from above, but this ensures integrity to the other table.
        involved_id             int NOT NULL REFERENCES complaint.involved(id) ON DELETE CASCADE,
        -- Who is doing the accompanying.
        companion_persona_id    int NOT NULL REFERENCES core.personas(id),
        UNIQUE(involved_id, companion_persona_id),
        is_withdrawn  boolean NOT NULL DEFAULT FALSE
    );
    GRANT SELECT ON complaint.companions TO cdb_persona;
    GRANT INSERT, UPDATE (is_withdrawn), DELETE ON complaint.companions TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.companions_id_seq TO cdb_admin;

    -- people, who are blocked from "meeting" within the complaint process
    CREATE TABLE complaint.companion_incompatibles (
        id            serial PRIMARY KEY,
        blocker_id    int NOT NULL REFERENCES core.personas(id),
        blocked_id    int NOT NULL REFERENCES core.personas(id),
        UNIQUE(blocker_id, blocked_id)
    );
    GRANT SELECT, INSERT, DELETE ON complaint.companion_incompatibles TO cdb_persona;

    -- like event helpers, may access limited information on measures
    CREATE TABLE complaint.enforcers (
        id                      serial PRIMARY KEY,
        persona_id              integer UNIQUE NOT NULL REFERENCES core.personas(id)
    );
    GRANT SELECT ON complaint.enforcers TO cdb_persona;
    GRANT INSERT, DELETE ON complaint.enforcers TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.enforcers_id_seq TO cdb_admin;

    -- like event helpers, may access limited information on involved parties
    CREATE TABLE complaint.monitors (
        id                      serial PRIMARY KEY,
        persona_id              integer UNIQUE NOT NULL REFERENCES core.personas(id)
    );
    GRANT SELECT ON complaint.monitors TO cdb_persona;
    GRANT INSERT, DELETE ON complaint.monitors TO cdb_admin;
    GRANT SELECT, UPDATE ON complaint.monitors_id_seq TO cdb_admin;

    -- logs changes and decryption
    CREATE TABLE complaint.log (
            id                      bigserial PRIMARY KEY,
            ctime                   timestamp WITH TIME ZONE DEFAULT now(),
            -- see cdedb.database.constants.ComplaintLogCodes
            code                    integer NOT NULL,
            submitted_by            integer REFERENCES core.personas(id),
            case_id                 integer REFERENCES complaint.cases(id),
            -- affected user
            persona_id              integer REFERENCES core.personas(id),
            companion_id            integer REFERENCES core.personas(id),
            change_note             varchar
    );
    CREATE INDEX event_log_code_idx ON complaint.log(code);
    CREATE INDEX event_log_event_id_idx ON complaint.log(case_id);
    GRANT SELECT, INSERT ON complaint.log TO cdb_persona;
    GRANT SELECT, UPDATE ON complaint.log_id_seq TO cdb_persona;
    GRANT UPDATE (change_note), DELETE ON complaint.log TO cdb_admin;
COMMIT;
