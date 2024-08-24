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
           loc_id           varchar,
           postal_code      varchar,
           long             float8,
           lat              float8,
           name             varchar
    );
    COPY t
    FROM '/cdedb2/tests/ancillary_files/PLZ.tab'
    DELIMITER E'\t'
    CSV HEADER;
    INSERT INTO core.postal_code_locations(postal_code, earth_location, lat, long, name)
    SELECT postal_code, ll_to_earth(lat, long), lat, long, name FROM t;
    DROP TABLE t;
COMMIT;
