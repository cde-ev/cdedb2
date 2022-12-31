#!/bin/bash
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2022-11-31_pronouns_privileges.sql
