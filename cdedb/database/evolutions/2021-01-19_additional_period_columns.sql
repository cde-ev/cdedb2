BEGIN;
    ALTER TABLE cde.period ADD COLUMN archival_notifications integer NOT NULL DEFAULT 0;
    ALTER TABLE cde.period ADD COLUMN archival_count integer NOT NULL DEFAULT 0;
COMMIT;
