#!/usr/bin/env bash
set -e

echo "Creating backup of 'past_event' schema at '/home/cdedb/past_event_dump.sql'."
sudo -u cdb pg_dump -d cdb --schema "past_event" | sudo -u cdedb tee /home/cdedb/past_event_dump.sql > /dev/null || (echo "Error creating backup, aborting."; exit)

echo "Running migration."
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2026-01-28_migrate-past-participants.sql > /dev/null

echo "done"
