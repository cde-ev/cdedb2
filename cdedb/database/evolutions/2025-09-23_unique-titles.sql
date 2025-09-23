BEGIN;
    ALTER TABLE event.event_fees ADD UNIQUE event_fee_title_constraint (event_id, title);
    ALTER TABLE assembly.candidates ADD UNIQUE candidate_title_constraint (ballot_id, title);
COMMIT;
