BEGIN;
    GRANT SELECT (ml_type, is_active) ON ml.mailinglists TO cdb_ldap;
COMMIT;
