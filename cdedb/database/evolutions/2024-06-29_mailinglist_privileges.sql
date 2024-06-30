BEGIN;
    REVOKE INSERT ON ml.mailinglists FROM cdb_admin;
    GRANT INSERT ON ml.mailinglists TO cdb_persona;
COMMIT;
