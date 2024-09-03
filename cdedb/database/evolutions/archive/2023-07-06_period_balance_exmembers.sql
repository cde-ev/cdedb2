BEGIN;
    ALTER TABLE cde.org_period ADD COLUMN exmember_state integer REFERENCES core.personas(id);
    ALTER TABLE cde.org_period ADD COLUMN exmember_done timestamp WITH TIME ZONE DEFAULT NULL;
COMMIT;
