BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN convert_html assembly.assemblies ADD COLUMN convert_html boolean NOT NULL DEFAULT TRUE;
COMMIT;
