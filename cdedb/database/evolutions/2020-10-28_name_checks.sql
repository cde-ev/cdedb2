BEGIN;
    -- DROP existing, unnamed checks
    ALTER TABLE core.personas DROP CONSTRAINT personas_check;
    ALTER TABLE core.personas DROP CONSTRAINT personas_check1;
    ALTER TABLE core.personas DROP CONSTRAINT personas_check2;
    ALTER TABLE core.personas DROP CONSTRAINT personas_check3;
    ALTER TABLE core.personas DROP CONSTRAINT personas_check4;
    -- DROP checks that might exist if people have evolved their database
    -- manually in weird ways
    ALTER TABLE core.personas DROP CONSTRAINT IF EXISTS personas_check5;
    ALTER TABLE core.personas DROP CONSTRAINT IF EXISTS personas_check6;
    -- CREATE named, partially improved checks
    ALTER TABLE core.personas ADD CONSTRAINT personas_realm_gender
        CHECK((NOT is_cde_realm AND NOT is_event_realm) OR gender IS NOT NULL);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_balance
        CHECK(NOT is_cde_realm OR balance IS NOT NULL);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_consent
        CHECK(NOT is_cde_realm OR decided_search IS NOT NULL);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_trial
        CHECK(NOT is_cde_realm OR trial_member IS NOT NULL);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_bub
        CHECK(NOT is_cde_realm OR bub_search IS NOT NULL);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_expuls
        CHECK(NOT is_cde_realm OR paper_expuls IS NOT NULL);
COMMIT;
