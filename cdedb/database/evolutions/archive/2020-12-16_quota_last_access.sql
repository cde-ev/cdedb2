BEGIN;
    ALTER TABLE core.quota ADD column last_access_hash varchar;
    GRANT UPDATE (last_access_hash) ON core.quota TO cdb_member;
COMMIT;
