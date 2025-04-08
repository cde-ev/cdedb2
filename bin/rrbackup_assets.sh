#!/bin/bash
#
# to be executed via crontab of the cdedb user
# 42 5 * * * /cdedb2/bin/rrbackup_assets.sh

sudo tar -C / -zcf //sic_temp/backups/cdedb-assets-backup-$(date +%u).tar.gz var/lib/cdedb
