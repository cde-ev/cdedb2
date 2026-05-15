#!/usr/bin/env sh

echo "Creating backup of 'questionnaire_rows' table at '/home/cdedb/questionnaire_dump.sql'."
sudo -u cdb pg_dump -d cdb --table "event.questionnaire_rows" | sudo -u cdedb tee /home/cdedb/questionnaire_dump.sql > /dev/null || (echo "Error creating backup, aborting."; exit)

sudo -u www-cde uv run /cdedb2/cdedb/database/evolutions/2026-05-15_questionnaire-magic.py
