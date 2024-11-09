BEGIN;
    ALTER TABLE assembly.ballots ADD COLUMN comment varchar DEFAULT NULL;
COMMIT;
