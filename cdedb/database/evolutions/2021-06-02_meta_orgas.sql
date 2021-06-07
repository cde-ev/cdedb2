BEGIN;
    ALTER TABLE event.orgas ADD CONSTRAINT event_unique_orgas
        UNIQUE(persona_id, event_id);
    ALTER TABLE assembly.presiders ADD CONSTRAINT assembly_unique_presiders
        UNIQUE(persona_id, assembly_id);
    ALTER TABLE ml.moderators ADD CONSTRAINT mailinglist_unique_moderators
        UNIQUE(persona_id, mailinglist_id);
    ALTER TABLE ml.whitelist ADD CONSTRAINT mailinglist_unique_whitelist
        UNIQUE(address, mailinglist_id)
COMMIT;
