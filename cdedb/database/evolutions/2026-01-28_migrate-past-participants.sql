BEGIN;
    -- Step 1: Extract participant and orga data into temporary table. Base orga status on institution.
    --   Deduplicate entries per event and persona, ORing the orga stati together.

    DROP TABLE IF EXISTS tmp_participant;

    SELECT
        p.persona_id,
        p.pevent_id,
        bit_or(
            CASE
                WHEN p.is_orga = FALSE THEN 0
                WHEN e.institution in (1, 200, 400, 1000) THEN 1
                ELSE 2
            END
        ) AS orga_status
    INTO tmp_participant
    FROM past_event.participants p
        JOIN past_event.events e ON p.pevent_id = e.id
    GROUP BY p.persona_id, p.pevent_id;

    -- Step 2: Extract course assignment and instructor data into temporary table.
    --   Track participants by persona id.

    DROP TABLE IF EXISTS tmp_course;

    SELECT persona_id, pevent_id, pcourse_id, is_instructor::integer AS instructor_status
    INTO tmp_course
    FROM past_event.participants WHERE pcourse_id IS NOT NULL;

    -- Step 3: Drop old participants data and modify table.

    -- SELECT id, pevent_id, persona_id, is_orga, pcourse_id, is_instructor FROM past_event.participants ORDER BY pevent_id, persona_id;
    TRUNCATE past_event.participants;
    ALTER SEQUENCE IF EXISTS past_event.participants_id_seq RESTART WITH 1;

    ALTER TABLE past_event.participants DROP COLUMN pcourse_id;
    ALTER TABLE past_event.participants DROP COLUMN is_orga;
    ALTER TABLE past_event.participants DROP COLUMN is_instructor;
    ALTER TABLE past_event.participants ADD COLUMN orga_status INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE past_event.participants ADD COLUMN music_status INTEGER NOT NULL DEFAULT 0;

    -- Step 4: Restore participants table from temporary table.

    INSERT INTO past_event.participants(persona_id, pevent_id, orga_status)
    SELECT * FROM tmp_participant
    ORDER BY pevent_id, persona_id;
    -- SELECT * FROM past_event.participants;

    -- Step 5: Create course participants table.

    CREATE TABLE past_event.course_participants (
        id                  serial PRIMARY KEY,
        participant_id      integer NOT NULL REFERENCES past_event.participants(id),
        pcourse_id          integer NOT NULL REFERENCES past_event.courses(id),
        instructor_status   integer NOT NULL DEFAULT 0,
        UNIQUE (participant_id, pcourse_id)
    );

    CREATE INDEX course_participants_pcourse_id_idx ON past_event.course_participants(pcourse_id);
    GRANT SELECT ON past_event.course_participants TO cdb_persona;
    GRANT INSERT, UPDATE, DELETE ON past_event.course_participants TO cdb_admin;
    GRANT SELECT, UPDATE ON past_event.course_participants_id_seq TO cdb_admin;

    -- Step 6: Populate course participants table. Use persona id to determine (new) participant id.

    INSERT INTO past_event.course_participants(participant_id, pcourse_id, instructor_status)
    SELECT p.id, tmp.pcourse_id, tmp.instructor_status
    FROM tmp_course tmp
        JOIN past_event.participants p ON tmp.persona_id = p.persona_id AND tmp.pevent_id = p.pevent_id
    ORDER BY id, pcourse_id;
    -- SELECT * FROM past_event.course_participants;

    -- Step 7 (optional): View sample result for one persona to verify.

    -- SELECT e.title, p.orga_status
    -- FROM past_event.participants p
    --     LEFT JOIN past_event.events e ON p.pevent_id = e.id
    -- WHERE p.persona_id = 20109;
    --
    -- SELECT c.title, cp.instructor_status
    -- FROM past_event.course_participants cp
    --     LEFT JOIN past_event.participants p ON cp.participant_id = p.id
    --     LEFT JOIN past_event.courses c ON cp.pcourse_id = c.id
    -- WHERE p.persona_id = 20109;
COMMIT;
