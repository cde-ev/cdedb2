BEGIN;
    ALTER TABLE cde.org_period ADD COLUMN billing_count integer NOT NULL DEFAULT 0;
    ALTER TABLE cde.org_period ADD COLUMN semester_done timestamp WITH TIME ZONE DEFAULT NULL;
    ALTER TABLE cde.expuls_period ADD COLUMN addresscheck_count integer NOT NULL DEFAULT 0;
    ALTER TABLE cde.expuls_period ADD COLUMN expuls_done timestamp WITH TIME ZONE DEFAULT NULL;
COMMIT;
