BEGIN;
    DROP ROLE IF EXISTS cdb_ldap;
    CREATE USER cdb_ldap            PASSWORD '1234567890zyxwvutsrqponmlkjihg';
    GRANT cdb_ldap TO cdb;

    GRANT USAGE ON SCHEMA core TO cdb_ldap;
    GRANT SELECT (id, username, password_hash, is_active, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin,
                  is_event_admin, is_ml_admin, is_assembly_admin, is_cdelokal_admin, is_auditor, is_cde_realm,
                  is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived, is_purged
                 ) ON core.personas TO cdb_ldap;
    GRANT SELECT (display_name, given_names, family_name, title, name_supplement) ON core.personas TO cdb_ldap;

    GRANT USAGE ON SCHEMA event TO cdb_ldap;
    GRANT SELECT (id, title, shortname) ON event.events TO cdb_ldap;
    GRANT SELECT ON event.orgas TO cdb_ldap;

    GRANT USAGE ON SCHEMA assembly TO cdb_ldap;
    GRANT SELECT (id, title, shortname) ON assembly.assemblies TO cdb_ldap;
    GRANT SELECT ON assembly.presiders TO cdb_ldap;

    GRANT USAGE ON SCHEMA ml TO cdb_ldap;
    GRANT SELECT (id, address, title) ON ml.mailinglists TO cdb_ldap;
    GRANT SELECT ON ml.subscription_states TO cdb_ldap;
    GRANT SELECT ON ml.moderators TO cdb_ldap;

COMMIT;
