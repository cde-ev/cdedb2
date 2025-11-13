#!/bin/bash
#
# to be executed via crontab of the www-cde user
# 42 5 * * * /cdedb2/bin/rrbackup_assets.sh

cd /var/lib/cdedb/event_keeper/
for D in */; do(cd "$D" && sudo -u www-cde git maintenance run); done
tar -C / -zcf //sic_temp/backups/cdedb-assets-backup-$(date +%u).tar.gz var/lib/cdedb
