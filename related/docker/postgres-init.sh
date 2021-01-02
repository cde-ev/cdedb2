#!/bin/sh
# this file gets run during first container start
set -e

psql <<-EOSQL
    CREATE USER nobody PASSWORD 'nobody';
    CREATE DATABASE nobody WITH OWNER = nobody TEMPLATE = template0 ENCODING = 'UTF8';
    ALTER DATABASE nobody SET datestyle TO 'ISO, YMD';
EOSQL
