BEGIN;
    GRANT SELECT (is_active) ON ml.mailinglists TO cdb_ldap;
COMMIT;
