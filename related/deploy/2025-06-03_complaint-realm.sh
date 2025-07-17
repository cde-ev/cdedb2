#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/dedb/database/evolutions/2025-06-03_complaint-realm.sql
