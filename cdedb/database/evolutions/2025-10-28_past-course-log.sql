BEGIN;
    ALTER TABLE past_event.log ADD COLUMN pcourse_id integer REFERENCES past_event.courses(id);
COMMIT;
