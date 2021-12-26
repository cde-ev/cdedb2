BEGIN;
    DROP INDEX assembly.idx_shortname_constraint;
    ALTER TABLE assembly.candidates ADD CONSTRAINT candidate_shortname_constraint UNIQUE (ballot_id, shortname) DEFERRABLE INITIALLY IMMEDIATE;
COMMIT;
