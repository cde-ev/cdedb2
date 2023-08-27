BEGIN;
    CREATE UNIQUE INDEX changelog_persona_id_pending ON core.changelog(persona_id) WHERE code = 1;
COMMIT;
