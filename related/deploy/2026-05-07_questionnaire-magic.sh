#!/usr/bin/env bash

echo "Creating backup of 'questionnaire_rows' table at '/home/cdedb/questionnaire_dump.sql'."
sudo -u cdb pg_dump -d cdb --table "event.questionnaire_rows" | sudo -u cdedb tee /home/cdedb/questionnaire_dump.sql > /dev/null || (echo "Error creating backup, aborting."; exit)

# Work around limitation of setting falsy environment variables.
if [ -v "SCRIPT_DRY_RUN" ]; then
    DRY_RUN="$SCRIPT_DRY_RUN"
else
    DRY_RUN="true"
fi

sudo -u www-cde SCRIPT_PERSONA_ID="$SCRIPT_PERSONA_ID" SCRIPT_DRY_RUN="$DRY_RUN" uv run /cdedb2/cdedb/database/evolutions/2026-05-15_questionnaire-magic.py
