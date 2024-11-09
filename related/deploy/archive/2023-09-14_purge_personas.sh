#!/bin/bash
sudo -u www-data SCRIPT_DRY_RUN="" /cdedb2/bin/repurge_personas.py
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2023-09-14_purge_personas.sql
