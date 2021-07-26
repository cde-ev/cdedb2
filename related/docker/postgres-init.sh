#!/bin/sh
# this file gets run during first container start
set -e

psql <<-EOSQL
    CREATE USER nobody PASSWORD 'nobody';
    CREATE DATABASE nobody WITH OWNER = nobody TEMPLATE = template0 ENCODING = 'UTF8';
    ALTER DATABASE nobody SET datestyle TO 'ISO, YMD';
EOSQL

# replace lines which grant all users trust to only grant trust to postgres
# this is required for e.g. podman-compose where all containers share an ip
# and consequently even cdb users would not require a password which breaks test_setup
sed -i -r 's/(host\s+\w+\s+)all(\s+\S+\s+trust)/\1postgres\2/g' /var/lib/postgresql/data/pg_hba.conf
