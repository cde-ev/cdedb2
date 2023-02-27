BEGIN;
    ALTER TABLE cde.org_period ADD COLUMN exmember_balance numeric(11, 2) NOT NULL DEFAULT 0;
    ALTER TABLE cde.org_period ADD COLUMN exmember_count integer NOT NULL DEFAULT 0,;
COMMIT;
