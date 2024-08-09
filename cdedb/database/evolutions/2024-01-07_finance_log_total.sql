BEGIN;
    ALTER TABLE cde.finance_log RENAME total TO member_total;
    ALTER TABLE cde.finance_log ADD COLUMN total NUMERIC(11, 2) NOT NULL DEFAULT -1;
    ALTER TABLE cde.finance_log ALTER COLUMN total DROP DEFAULT;
COMMIT;
