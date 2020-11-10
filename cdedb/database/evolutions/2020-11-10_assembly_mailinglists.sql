BEGIN;
    ALTER TABLE assembly.assemblies ADD COLUMN shortname VARCHAR;
    UPDATE assembly.assemblies SET shortname = 'placeholder';
    ALTER TABLE assembly.assemblies ALTER COLUMN shortname SET NOT NULL;
    ALTER TABLE assembly.assemblies RENAME COLUMN mail_address TO presider_address;
COMMIT;