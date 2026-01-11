#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2025-11-23_ballot_log.sql
