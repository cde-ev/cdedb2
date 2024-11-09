#!/bin/sh

SCRIPT_NAME=/db exec /usr/bin/gunicorn \
    --user www-cde \
    --group www-data \
    --chdir /cdedb2 \
    \
    --forwarded-allow-ips="*" \
    --workers 4 \
    --bind localhost:8998 \
    --daemon \
    --enable-stdio-inheritance \
    --reload \
    \
    --limit-request-line 0 \
    --limit-request-fields 0 \
    wsgi.cdedb-app:application
