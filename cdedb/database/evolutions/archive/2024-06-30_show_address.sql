BEGIN;
    ALTER TABLE core.personas ADD COLUMN show_address boolean NOT NULL DEFAULT TRUE;
    ALTER TABLE core.personas ADD COLUMN show_address2 boolean NOT NULL DEFAULT TRUE;
    ALTER TABLE core.changelog ADD COLUMN show_address boolean NOT NULL DEFAULT TRUE;
    ALTER TABLE core.changelog ADD COLUMN show_address2 boolean NOT NULL DEFAULT TRUE;
    GRANT UPDATE (show_address) ON core.personas TO cdb_persona;
    GRANT UPDATE (show_address2) ON core.personas TO cdb_member;
COMMIT;
