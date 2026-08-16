BEGIN;
    ALTER TABLE event.event_fees ADD CONSTRAINT event_fee_title_constraint UNIQUE (event_id, title) DEFERRABLE INITIALLY IMMEDIATE;
    ALTER TABLE assembly.candidates ADD CONSTRAINT candidate_title_constraint UNIQUE (ballot_id, title) DEFERRABLE INITIALLY IMMEDIATE;
COMMIT;
