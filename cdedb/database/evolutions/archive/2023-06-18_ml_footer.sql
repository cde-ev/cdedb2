BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN additional_footer varchar;
COMMIT;
