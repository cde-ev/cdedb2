#!/bin/sh
set -e

cd /cdedb2

# Be paranoid about filesystem locations. This should not be necessary, but
# sadly is. Can probably be removed after #3427 is resolved.
if [ ! -e /var/log/cdedb ]; then
    python3 -m cdedb filesystem --owner www-cde log create
fi
if [ ! -e /var/lib/cdedb ]; then
    python3 -m cdedb filesystem --owner www-cde storage create
fi

export SCRIPT_NAME=/db
sudo --preserve-env=SCRIPT_NAME -u www-cde /usr/bin/gunicorn --forwarded-allow-ips="*" \
     -w 4 --bind localhost:8998 wsgi.cdedb-app:application --daemon
unset SCRIPT_NAME

cd /

export APACHE_HTTPD='exec /usr/sbin/apache2'
exec apachectl -DFOREGROUND
