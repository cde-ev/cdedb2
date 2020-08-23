-- Create the SQL views necessary for the member stats page. Part of PR #1374.
BEGIN;

CREATE VIEW cde.member_stats AS (
    SELECT
        num_members, num_searchable, num_ex_members
    FROM
        (
            SELECT COUNT(*) AS num_members
            FROM core.personas
            WHERE is_member = True
        ) AS member_count,
        (
            SELECT COUNT(*) AS num_searchable
            FROM core.personas
            WHERE is_member = True AND is_searchable = True
        ) AS searchable_count,
        (
            SELECT COUNT(*) AS num_ex_members
            FROM core.personas
            WHERE is_cde_realm = True AND is_member = False AND is_archived = False
        ) AS ex_member_count
);

CREATE VIEW cde.members_by_country AS (
    SELECT COUNT(*) AS num, COALESCE(country, 'Deutschland') AS datum
    FROM core.personas
    WHERE is_member = True AND location IS NOT NULL
    GROUP BY datum
    ORDER BY
        num DESC,
        datum ASC
);

CREATE VIEW cde.members_by_plz AS (
    SELECT COUNT(*) AS num, postal_code AS datum
    FROM core.personas
    WHERE is_member = True AND postal_code IS NOT NULL
    GROUP BY datum
    ORDER BY
        num DESC,
        datum ASC
);

CREATE VIEW cde.members_by_city AS (
    SELECT COUNT(*) AS num, location AS datum
    FROM core.personas
    WHERE is_member = True AND location IS NOT NULL
    GROUP BY datum
    ORDER BY
        num DESC,
        datum ASC
);

CREATE VIEW cde.members_by_birthday AS (
    SELECT COUNT(*) AS num, EXTRACT(year FROM birthday)::integer AS datum
    FROM core.personas
    WHERE is_member = True AND birthday IS NOT NULL
    GROUP BY datum
    ORDER BY
        -- num DESC,
        datum ASC
);

CREATE VIEW cde.members_by_first_event AS (
    SELECT
        COUNT(*) AS num, EXTRACT(year FROM min_tempus.tempus)::integer AS datum
    FROM
        (
            SELECT persona.id, MIN(pevents.tempus) as tempus
            FROM
                (
                    SELECT id FROM core.personas
                    WHERE is_member = TRUE
                ) as persona
                LEFT OUTER JOIN (
                    SELECT DISTINCT persona_id, pevent_id
                    FROM past_event.participants
                ) AS participants ON persona.id = participants.persona_id
                LEFT OUTER JOIN (
                    SELECT id, tempus
                    FROM past_event.events
                ) AS pevents ON participants.pevent_id = pevents.id
            WHERE
                pevents.id IS NOT NULL
            GROUP BY
                persona.id
        ) AS min_tempus
    GROUP BY
        datum
    ORDER BY
        -- num DESC,
        datum ASC
);

GRANT SELECT ON cde.member_stats TO cdb_member;
GRANT SELECT ON cde.members_by_country TO cdb_member;
GRANT SELECT ON cde.members_by_plz TO cdb_member;
GRANT SELECT ON cde.members_by_city TO cdb_member;
GRANT SELECT ON cde.members_by_birthday TO cdb_member;
GRANT SELECT ON cde.members_by_first_event TO cdb_member;

COMMIT;
