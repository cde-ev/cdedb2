-- Fixes #1326, allowing cron jobs to make log entries in all realms.
BEGIN;
    ALTER TABLE cde.log ALTER COLUMN submitted_by DROP NOT NULL;
    ALTER TABLE cde.finance_log ALTER COLUMN submitted_by DROP NOT NULL;
    ALTER TABLE past_event.log ALTER COLUMN submitted_by DROP NOT NULL;
    ALTER TABLE event.log ALTER COLUMN submitted_by DROP NOT NULL;
    ALTER TABLE assembly.log ALTER COLUMN submitted_by DROP NOT NULL;
COMMIT;