BEGIN;
    ALTER TABLE core.personas ADD CONSTRAINT personas_active_archived
            CHECK (NOT (is_archived AND is_active));
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_meta
        CHECK (NOT is_meta_admin OR is_cde_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_core
        CHECK (NOT is_core_admin OR is_cde_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_cde
        CHECK (NOT is_cde_admin OR is_cde_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_finance
        CHECK (NOT is_finance_admin OR is_cde_admin);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_event
        CHECK (NOT is_event_admin OR is_event_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_ml
        CHECK (NOT is_ml_admin OR is_ml_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_assembly
        CHECK (NOT is_assembly_admin OR is_assembly_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_admin_cdelokal
        CHECK (NOT is_cdelokal_admin OR is_ml_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_realm_cde_implicits
        CHECK (NOT is_cde_realm OR (is_event_realm AND is_assembly_realm));
    ALTER TABLE core.personas ADD CONSTRAINT personas_realm_event_implicits
        CHECK (NOT is_event_realm OR is_ml_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_realm_assembly_implicits
        CHECK (NOT is_assembly_realm OR is_ml_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_member_implicits
        CHECK (NOT is_member OR is_cde_realm);
    ALTER TABLE core.personas ADD CONSTRAINT personas_archived_purged
        CHECK (NOT is_purged OR is_archived);
COMMIT;
