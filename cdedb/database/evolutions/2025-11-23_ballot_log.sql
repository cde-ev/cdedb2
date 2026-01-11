BEGIN;
    ALTER TABLE assembly.log ADD COLUMN ballot_id integer REFERENCES assembly.ballots(id) ON DELETE SET NULL;
COMMIT;
