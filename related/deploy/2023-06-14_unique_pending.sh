#!/bin/bash
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2023-06-14_unique_pending.sql
