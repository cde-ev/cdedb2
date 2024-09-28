BEGIN;
    DROP SCHEMA IF EXISTS ldap CASCADE;
    DROP TABLE IF EXISTS ldap_oc_mappings CASCADE;
    DROP TABLE IF EXISTS ldap_attr_mappings CASCADE;
    DROP VIEW IF EXISTS ldap_entries CASCADE;
    DROP VIEW IF EXISTS ldap_entry_objclasses CASCADE;
END;
