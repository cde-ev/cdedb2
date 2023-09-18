BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN roster_visibility integer NOT NULL;
    UPDATE ml.mailinglists SET roster_visibility=1;
COMMIT;
