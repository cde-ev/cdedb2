DO $$
    DECLARE onetable varchar;
    BEGIN
        -- suppress uber verbose output - sadly this is not possible via stdout/err distinction in Makefile
        SET client_min_messages TO warning;
        FOR onetable IN
            SELECT table_schema || '.' || table_name AS atable FROM information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
        LOOP
            -- RAISE NOTICE 'process %', onetable;
            EXECUTE 'TRUNCATE ' || onetable || ' CASCADE';
        END LOOP;
    END;
$$;
