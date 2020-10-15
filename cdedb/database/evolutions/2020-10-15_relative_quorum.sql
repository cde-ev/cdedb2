BEGIN;
    ALTER TABLE assembly.ballots RENAME COLUMN quorum TO abs_quorum;
    ALTER TABLE assembly.ballots ADD COLUMN rel_quorum integer NOT NULL DEFAULT 0;
COMMIT;
