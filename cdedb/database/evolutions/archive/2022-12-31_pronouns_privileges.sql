BEGIN;
    GRANT SELECT, UPDATE (pronouns, pronouns_nametag, pronouns_profile) ON core.personas TO cdb_persona;
END;
