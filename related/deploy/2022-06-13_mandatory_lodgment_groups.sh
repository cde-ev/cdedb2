#!/bin/bash
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2022-06-13_mandatory_lodgement_groups.sql
