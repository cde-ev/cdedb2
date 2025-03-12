#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2024-05-08_fix_changelog_realm_bits.sql

sudo -u www-cde bin/validate_personas.py
