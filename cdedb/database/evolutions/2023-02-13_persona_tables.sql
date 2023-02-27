BEGIN;
    REVOKE ALL ON core.personas FROM cdb_persona;
    REVOKE ALL ON core.personas FROM cdb_member;
    GRANT SELECT (id, username, password_hash, is_active, is_meta_admin, is_core_admin, is_cde_admin, is_finance_admin, is_event_admin, is_ml_admin, is_assembly_admin, is_cdelokal_admin, is_auditor, is_cde_realm, is_event_realm, is_ml_realm, is_assembly_realm, is_member, is_searchable, is_archived, is_purged) ON core.personas TO cdb_anonymous, cdb_ldap;
    GRANT SELECT (display_name, given_names, family_name, title, name_supplement) ON core.personas TO cdb_ldap;
    -- required for _changelog_resolve_change_unsafe
    GRANT SELECT ON core.personas TO cdb_persona;
    GRANT UPDATE (display_name, given_names, family_name, title, name_supplement, pronouns, pronouns_nametag, pronouns_profile, gender, birthday, telephone, mobile, address_supplement, address, postal_code, location, country, fulltext, username, password_hash) ON core.personas TO cdb_persona;
    GRANT UPDATE (birth_name, address_supplement2, address2, postal_code2, location2, country2, weblink, specialisation, affiliation, timeline, interests, free_form, decided_search, bub_search, foto, paper_expuls, is_searchable) ON core.personas TO cdb_member;
    -- includes notes in addition to cdb_member
    GRANT UPDATE, INSERT ON core.personas TO cdb_admin;
    GRANT SELECT, UPDATE ON core.personas_id_seq TO cdb_admin;
    CREATE INDEX changelog_persona_id_idx ON core.changelog(persona_id);
END;
