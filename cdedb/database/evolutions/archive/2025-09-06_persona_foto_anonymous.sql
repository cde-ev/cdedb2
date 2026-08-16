BEGIN;
    GRANT SELECT (foto) ON core.personas TO cdb_anonymous, cdb_ldap;
COMMIT;
