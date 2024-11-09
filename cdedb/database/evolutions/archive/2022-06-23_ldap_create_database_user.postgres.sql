BEGIN;
    DROP ROLE IF EXISTS cdb_ldap;
    CREATE USER cdb_ldap            PASSWORD '1234567890zyxwvutsrqponmlkjihg';
    GRANT cdb_ldap TO cdb;
COMMIT;
