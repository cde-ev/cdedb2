-- Unifies column names of log tables and changelog.
-- change_status -> code
-- additional_info -> change_note
BEGIN;
    ALTER TABLE cde.log RENAME COLUMN additional_info TO change_note;
    ALTER TABLE cde.finance_log RENAME COLUMN additional_info TO change_note;
    ALTER TABLE event.log RENAME COLUMN additional_info TO change_note;
    ALTER TABLE assembly.log RENAME COLUMN additional_info TO change_note;
    ALTER TABLE past_event.log RENAME COLUMN additional_info TO change_note;
    ALTER TABLE core.log RENAME COLUMN additional_info TO change_note;

    DROP INDEX idx_changelog_change_status;
    ALTER TABLE core.changelog RENAME COLUMN change_status TO code;
    CREATE INDEX idx_changelog_code ON core.changelog(code);
COMMIT;
