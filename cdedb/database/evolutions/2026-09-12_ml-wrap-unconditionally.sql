BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN wrap_unconditionally boolean NOT NULL DEFAULT TRUE;
COMMIT;
