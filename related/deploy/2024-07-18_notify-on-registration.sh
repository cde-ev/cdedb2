#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2024-07-18_notify-on-registration.sql
