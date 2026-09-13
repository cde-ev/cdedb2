BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN mitigate_unconditionally boolean NOT NULL DEFAULT TRUE;
COMMIT;
