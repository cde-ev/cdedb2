BEGIN;
    -- If everything went according to plan in the past we should not need
    -- to delete the previous quota data. If not, it shouldn't hurt and might
    -- actually be a good idea privacy wise to do this.
    -- DELETE FROM core.quota;
    DROP INDEX core.idx_quota_persona_id_qdate;
    CREATE UNIQUE INDEX idx_quota_persona_id_qdate
        ON core.quota(qdate, persona_id);
COMMIT;