BEGIN;
    GRANT SELECT, UPDATE ON complaint.authors_id_seq TO cdb_admin;
COMMIT;
