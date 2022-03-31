#!/bin/sh
set -e

if [ ! -f /etc/ssl/apache2/server.pem ] || [ ! -f /etc/ssl/apache2/server.key ]; then
    mkdir -p /etc/ssl/apache2
    openssl req \
        -x509 \
        -newkey rsa:4096 \
        -out /etc/ssl/apache2/server.pem \
        -keyout /etc/ssl/apache2/server.key \
        -days 365 \
        -nodes \
        -subj "/C=DE/O=CdE e.V./CN=cdedb.local/emailAddress=cdedb@lists.cde-ev.de"
fi

# If this is the first run of the container, perform some initialization
if [ ! -e /etc/cdedb/container_already_initalized ]; then
    # Create the log directory. Ensure that www-data owns everything.
    python3 -m cdedb filesystem --owner www-data log create

    # Create the storage directory. Ensure that www-data owns everything.
    python3 -m cdedb filesystem --owner www-data storage create

    # Create the database users and schema.
    python3 -m cdedb db create-users
    python3 -m cdedb db create

    # Compile the translations and populate the db with sample data.
    # Most of the above would be done by apply-sample-data but we want to be explicit.
    make i18n-compile
    python3 -m cdedb dev apply-sample-data --owner www-data

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
