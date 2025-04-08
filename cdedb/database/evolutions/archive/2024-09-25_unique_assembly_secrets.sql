BEGIN;
    ALTER TABLE assembly.attendees ADD CONSTRAINT attendees_secret_key UNIQUE (secret);
COMMIT;
