BEGIN;
    REVOKE SELECT ON past_event.events FROM cdb_member;
    GRANT SELECT ON past_event.events TO cdb_persona;
    REVOKE UPDATE, INSERT ON past_event.courses FROM cdb_persona;
    GRANT UPDATE, INSERT ON past_event.courses TO cdb_admin;
COMMIT;
