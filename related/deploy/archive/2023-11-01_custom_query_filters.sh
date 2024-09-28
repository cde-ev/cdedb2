#!/bin/bash
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2023-11-01_custom_query_filters.sql
