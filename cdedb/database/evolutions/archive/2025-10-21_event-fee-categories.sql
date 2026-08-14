BEGIN;
    ALTER TABLE event.registrations ADD COLUMN amount_owed_by_category jsonb NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE event.registrations ADD COLUMN amount_owed_by_budget jsonb NOT NULL DEFAULT '{}'::jsonb;
COMMIT;
