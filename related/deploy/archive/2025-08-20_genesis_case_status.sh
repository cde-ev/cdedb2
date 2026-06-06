#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2025-08-20_genesis_case_status.sql
