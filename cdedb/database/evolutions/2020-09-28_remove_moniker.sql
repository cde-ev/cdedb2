BEGIN;
    ALTER TABLE core.cron_store RENAME COLUMN moniker TO title;
    ALTER TABLE past_event.institutions RENAME COLUMN moniker TO shortname;
    ALTER TABLE event.lodgement_groups RENAME COLUMN moniker TO title;
    ALTER TABLE event.lodgements RENAME COLUMN moniker TO title;
    ALTER TABLE assembly.candidates RENAME COLUMN description TO title;
    ALTER TABLE assembly.candidates RENAME COLUMN moniker TO shortname;

    DROP INDEX assembly.idx_moniker_constraint;
    CREATE UNIQUE INDEX idx_shortname_constraint
        ON assembly.candidates(ballot_id, shortname);
COMMIT;
