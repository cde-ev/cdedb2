-- Part of PR #1322. Make lastschrifts deletable.
BEGIN;
    GRANT DELETE ON cde.lastschrift TO cdb_admin;
    GRANT DELETE ON cde.lastschrift_transactions TO cdb_admin;
COMMIT;
