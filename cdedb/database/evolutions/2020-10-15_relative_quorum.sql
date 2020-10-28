BEGIN;
    ALTER TABLE assembly.ballots ADD COLUMN abs_quorum integer NOT NULL DEFAULT 0;
    UPDATE assembly.ballots SET abs_quorum = quorum;
    ALTER TABLE assembly.ballots ADD COLUMN rel_quorum integer NOT NULL DEFAULT 0;
    ALTER TABLE assembly.ballots ALTER COLUMN quorum DROP NOT NULL;
    ALTER TABLE assembly.ballots ALTER COLUMN quorum DROP DEFAULT;
COMMIT;
