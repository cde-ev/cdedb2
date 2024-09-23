BEGIN;
    CREATE EXTENSION IF NOT EXISTS earthdistance CASCADE;
    DROP TABLE IF EXISTS core.postal_code_locations;
    CREATE TABLE core.postal_code_locations (
            postal_code     varchar PRIMARY KEY,
            name            varchar,
            earth_location  earth,
            lat             float8,
            long            float8
    );
    GRANT SELECT ON core.postal_code_locations TO cdb_persona;

    ALTER TABLE core.postal_code_locations OWNER TO cdb;

    CREATE TEMPORARY TABLE t (
           postal_code      varchar,
           description      varchar,
           inhabitants      integer,
           area             float8,
           lat              float8,
           long             float8
    );
    COPY t
    FROM '/cdedb2/tests/ancillary_files/plz.csv'
    DELIMITER ','
    CSV HEADER;
    INSERT INTO core.postal_code_locations(postal_code, earth_location, lat, long, name)
    SELECT
        postal_code, ll_to_earth(lat, long),
        lat, long,
        TRIM(REPLACE(REPLACE(description, postal_code, ''), E'\n', ' ')) FROM t;
    DROP TABLE t;
COMMIT;
