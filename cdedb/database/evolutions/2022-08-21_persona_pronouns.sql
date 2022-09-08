BEGIN;
    ALTER TABLE core.personas ADD COLUMN pronouns varchar DEFAULT NULL;
    ALTER TABLE core.personas ADD COLUMN pronouns_nametag boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.personas ADD COLUMN pronouns_profile boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.changelog ADD COLUMN pronouns varchar DEFAULT NULL;
    ALTER TABLE core.changelog ADD COLUMN pronouns_nametag boolean NOT NULL DEFAULT FALSE;
    ALTER TABLE core.changelog ADD COLUMN pronouns_profile boolean NOT NULL DEFAULT FALSE;
END;
