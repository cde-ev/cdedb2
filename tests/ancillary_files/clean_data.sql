DO $$
    DECLARE onetable varchar;
    BEGIN
        FOR onetable IN
            SELECT table_schema || '.' || table_name AS atable FROM information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
        LOOP
            -- RAISE NOTICE 'process %', onetable;
            EXECUTE 'TRUNCATE ' || onetable || ' CASCADE';
        END LOOP;
    END;
$$;
