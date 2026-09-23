BEGIN;
    ALTER TABLE ml.mailinglists ADD COLUMN immediate_notify boolean NOT NULL DEFAULT TRUE;
    -- Set to False for all cdelokal lists.
    UPDATE ml.mailinglists SET immediate_notify = (ml_type != 60);
COMMIT;
