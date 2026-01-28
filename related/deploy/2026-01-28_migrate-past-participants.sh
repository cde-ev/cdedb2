#!/usr/bin/env sh


sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2026-01-28_migrate-past-participants.sql
