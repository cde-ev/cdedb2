#!/bin/sh
set -e

cd /cdedb2
export SCRIPT_NAME=/db
sudo --preserve-env -u www-cde /usr/bin/gunicorn --forwarded-allow-ips="*" -w 4 --bind localhost:8998 wsgi.cdedb-app:application --daemon
unset SCRIPT_NAME

cd /
export APACHE_HTTPD='exec /usr/sbin/apache2'
exec apachectl -DFOREGROUND
