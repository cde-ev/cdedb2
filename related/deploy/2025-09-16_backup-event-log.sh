#!/usr/bin/env sh

sudo -u cdb pg_dump -U cdb --table event.log cdb | bzip2 > /home/cdb/backups/event_log_with_course_activity.sql.bz2
