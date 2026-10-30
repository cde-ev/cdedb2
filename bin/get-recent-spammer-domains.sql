
-- Get all rejected sender addresses of last 28 days from ml log

BEGIN;

    DROP TABLE IF EXISTS temp_rejected_senders;
    CREATE TEMP TABLE temp_rejected_senders AS SELECT
        SPLIT_PART(change_note, ' ', 1) AS sender_addr
        , SPLIT_PART(SPLIT_PART(change_note, ' ', 1), '@', 2) AS sender_domain
    FROM ml.log
    WHERE
        ctime >= now() - INTERVAL '28 days'
        AND code = 52;

    -- stats by address
    DROP TABLE IF EXISTS temp_sender_stats;
    CREATE TEMP TABLE temp_sender_stats AS SELECT DISTINCT
        sender_domain
        , COUNT(*) OVER(PARTITION BY sender_domain) AS anz
        , COUNT(*) OVER() AS anz_total
        , LPAD(
            ROUND(
                COUNT(*) OVER(PARTITION BY sender_domain) * 100.0 / COUNT(*) OVER()
                , 1
            ) || ' %',
            6,
            ' '
        ) AS anteil
    FROM temp_rejected_senders;

    SELECT *
    FROM temp_sender_stats
    WHERE anz > 1
    ORDER BY anz DESC LIMIT 50;


    -- stats by domain
    DROP TABLE IF EXISTS temp_addr_stats;
    CREATE TEMP TABLE temp_addr_stats AS SELECT DISTINCT
        sender_addr
        , COUNT(*) OVER(PARTITION BY sender_addr) AS anz
        , COUNT(*) OVER() AS anz_total
        , LPAD(
            ROUND(
                COUNT(*) OVER (PARTITION BY sender_addr) * 100.0 / COUNT(*) OVER ()
                , 1
            ) || ' %',
            6,
            ' '
        ) AS anteil
    FROM temp_rejected_senders;

    SELECT *
    FROM temp_addr_stats
    WHERE anz > 1
    ORDER BY anz DESC LIMIT 50;

ROLLBACK;

