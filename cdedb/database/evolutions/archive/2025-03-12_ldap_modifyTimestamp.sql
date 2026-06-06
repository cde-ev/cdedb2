BEGIN;
    GRANT SELECT (persona_id, ctime) ON core.changelog TO cdb_ldap;
    GRANT SELECT (event_id, persona_id, ctime, code) ON event.log TO cdb_ldap;
    GRANT SELECT (assembly_id, persona_id, ctime, code) ON assembly.log TO cdb_ldap;
    GRANT SELECT (mailinglist_id, persona_id, ctime, code) ON ml.log TO cdb_ldap;
COMMIT;
