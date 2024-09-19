#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2024-08-24_course_visibility.sql
