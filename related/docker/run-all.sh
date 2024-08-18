#!/bin/sh
set -e

cd /cdedb2

# Be paranoid about filesystem locations. This should not be necessary, but
# sadly is. Can probably be removed after #3427 is resolved.
if [ ! -e /var/log/cdedb ]; then
    python3 -m cdedb filesystem --owner www-cde --group www-data log create
fi
if [ ! -e /var/lib/cdedb ]; then
    python3 -m cdedb filesystem --owner www-cde --group www-data storage create
fi

/run-gunicorn.sh

cd /

export APACHE_HTTPD='exec /usr/sbin/apache2'
exec apachectl -DFOREGROUND
