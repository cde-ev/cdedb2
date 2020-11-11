-- This file is expected to produce errors in dev environments as the
-- deviations do not exist here. Hence it is mode ineffective by a rollback
-- at the end (which of course should be changed when actually applying
-- this).

BEGIN;
    ALTER TABLE core.changelog ALTER COLUMN is_finance_admin DROP NOT NULL;
    ALTER TABLE core.cron_store ALTER COLUMN title DROP UNIQUE;
    ALTER TABLE core.cron_store ALTER COLUMN title ADD UNIQUE;
    ALTER TABLE core.personas
        ADD CHECK(NOT is_cde_realm OR paper_expuls IS NOT NULL);
    ALTER TABLE events.events ALTER COLUMN camping_mat_field DROP FOREIGN KEY;
    ALTER TABLE events.events ALTER COLUMN camping_mat_field
        ADD FOREIGN KEY event.field_definitions(id);
    ALTER TABLE ml.mailinglists
        DROP CONSTRAINT mailinglists_domain_local_part_key;
    ALTER TABLE ml.mailinglists
        ADD CONSTRAINT mailinglists_unique_address UNIQUE(domain, local_part);
ROLLBACK;
