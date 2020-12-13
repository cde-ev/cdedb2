-- This file is expected to produce errors in dev environments as the
-- deviations do not exist here. Hence it is mode ineffective by a rollback
-- at the end (which of course should be changed when actually applying
-- this).

BEGIN;
    ALTER TABLE core.changelog ALTER COLUMN is_finance_admin DROP NOT NULL;
    ALTER TABLE core.cron_store DROP UNIQUE (title);
    ALTER TABLE core.cron_store ADD UNIQUE (title);
    ALTER TABLE core.personas
        ADD CHECK(NOT is_cde_realm OR paper_expuls IS NOT NULL);
    ALTER TABLE events.events DROP FOREIGN KEY (camping_mat_field);
    ALTER TABLE events.events ADD FOREIGN KEY (camping_mat_field)
        REFERENCES event.field_definitions(id);
    ALTER TABLE ml.mailinglists
        DROP CONSTRAINT mailinglists_domain_local_part_key;
    ALTER TABLE ml.mailinglists
        ADD CONSTRAINT mailinglists_unique_address UNIQUE(domain, local_part);
ROLLBACK;
