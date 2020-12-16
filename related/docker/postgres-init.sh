#!/bin/bash
# this file gets run during first container start
set -e

psql <<-EOSQL
    CREATE USER nobody PASSWORD 'nobody';
    CREATE DATABASE nobody WITH OWNER = nobody TEMPLATE = template0 ENCODING = 'UTF8';
    ALTER DATABASE nobody SET datestyle TO 'ISO, YMD';
EOSQL

psql --file=/opt/schema/cdedb-users.sql
psql --file=/opt/schema/cdedb-db.sql --variable=cdb_database_name=cdb
psql --file=/opt/schema/cdedb-db.sql --variable=cdb_database_name=cdb_test

psql --file=/opt/schema/cdedb-tables.sql --dbname=cdb --username=cdb
psql --file=/opt/schema/cdedb-tables.sql --dbname=cdb_test --username=cdb
# psql --file=/opt/mock/sample_data.sql --dbname=cdb --username=cdb
# psql --file=/opt/mock/sample_data.sql --dbname=cdb_test --username=cdb
