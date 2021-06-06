BEGIN;
    ALTER TABLE cde.org_period ADD COLUMN archival_notification_state integer REFERENCES core.personas(id);
    ALTER TABLE cde.org_period ADD COLUMN archival_notification_done timestamp WITH TIME ZONE DEFAULT NULL;
    ALTER TABLE cde.org_period ADD COLUMN archival_notification_count integer NOT NULL DEFAULT 0;
    ALTER TABLE cde.org_period ADD COLUMN archival_state integer REFERENCES core.personas(id);
    ALTER TABLE cde.org_period ADD COLUMN archival_done timestamp WITH TIME ZONE DEFAULT NULL;
    ALTER TABLE cde.org_period ADD COLUMN archival_count integer NOT NULL DEFAULT 0;
COMMIT;
