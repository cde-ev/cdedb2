#!/usr/bin/env sh

sudo -u postgres psql -d cdb -f /cdedb2/cdedb/database/evolutions/2024-06-11_postal_code_locations.postgres.sql
