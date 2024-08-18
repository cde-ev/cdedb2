#!/bin/sh

cd /cdedb2
export SCRIPT_NAME=/db
sudo --preserve-env=SCRIPT_NAME -u www-cde -g www-data /usr/bin/gunicorn \
     --forwarded-allow-ips="*" -w 4 --bind localhost:8998 --daemon --reload \
     --limit-request-line 0 --limit-request-fields 0 \
     wsgi.cdedb-app:application

