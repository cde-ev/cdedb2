BEGIN;
    ALTER TABLE ml.subscription_addresses ADD UNIQUE (address, mailinglist_id);
COMMIT;
