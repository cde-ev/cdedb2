BEGIN;
    ALTER TABLE core.personas DROP CONSTRAINT personas_cde_balance;
    ALTER TABLE core.personas DROP CONSTRAINT personas_cde_donation;
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_balance CHECK(NOT is_cde_realm OR balance IS NOT NULL OR is_purged);
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_donation CHECK(NOT is_cde_realm OR balance IS NOT NULL);
COMMIT;
