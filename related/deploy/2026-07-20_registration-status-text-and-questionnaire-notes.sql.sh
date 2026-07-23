#!/usr/bin/env sh

sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2026-07-20_registration-status-text-and-questionnaire-notes.sql
