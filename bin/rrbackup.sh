#!/bin/bash
#
# to be executed via crontab of the cdb user
# 42 * * * * /cdedb2/bin/rrbackup.sh
pg_dump -U cdb cdb | bzip2 > /home/cdb/backups/roundrobin/$(date +%w%H).sql.bz2
