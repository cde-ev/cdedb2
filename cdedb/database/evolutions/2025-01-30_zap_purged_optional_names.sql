BEGIN;
    UPDATE core.personas SET nickname = NULL, legal_given_names = NULL WHERE is_purged;
    UPDATE core.changelog SET nickname = NULL, legal_given_names = NULL WHERE is_purged;
COMMIT;
