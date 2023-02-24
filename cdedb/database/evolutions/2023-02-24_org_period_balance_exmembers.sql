BEGIN;
    ALTER TABLE cde.org_period ADD COLUMN balance_exmembers numeric(11, 2) NOT NULL DEFAULT 0;
COMMIT;
