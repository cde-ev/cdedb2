#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2025-01-30_zap_purged_optional_names.sql
