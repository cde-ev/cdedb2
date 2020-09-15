-- This file creates the database. This needs the postgres user, while
-- cdedb-tables will need the cdb user as acting agent.

DROP DATABASE IF EXISTS :cdb_database_name;
CREATE DATABASE :cdb_database_name WITH OWNER = cdb TEMPLATE = template0 ENCODING = 'UTF8';

ALTER DATABASE :cdb_database_name SET datestyle TO 'ISO, YMD';
