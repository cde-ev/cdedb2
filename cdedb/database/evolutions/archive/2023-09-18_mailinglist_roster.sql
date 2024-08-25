BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN roster_visibility integer NOT NULL DEFAULT 1;
    ALTER TABLE ml.mailinglists ALTER COLUMN roster_visibility DROP DEFAULT;
COMMIT;
