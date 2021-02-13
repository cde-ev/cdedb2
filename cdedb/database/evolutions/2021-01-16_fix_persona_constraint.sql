BEGIN;
    ALTER TABLE core.personas DROP CONSTRAINT personas_cde_balance;
    ALTER TABLE core.personas ADD CONSTRAINT personas_cde_balance CHECK(NOT is_cde_realm OR balance IS NOT NULL or is_purged);
COMMIT;
