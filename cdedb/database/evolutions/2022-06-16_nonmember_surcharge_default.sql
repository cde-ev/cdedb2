BEGIN;
    ALTER TABLE event.events ALTER COLUMN nonmember_surcharge SET DEFAULT 0;
COMMIT;
