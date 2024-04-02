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
    # Create the log and storage directory. Ensure that www-data owns everything.
    python3 -m cdedb filesystem --owner www-cde log create
    python3 -m cdedb filesystem --owner www-cde storage create

    # Populate the storage with sample data.
    python3 -m cdedb filesystem --owner www-cde storage populate

    # Create the database users and schema.
    python3 -m cdedb db create-users
    python3 -m cdedb db create

    # Wait for the database to come online
    pg_isready --host=cdb --timeout=15

    # Populate the database with sample data.
    python3 -m cdedb db populate

    # Compile the translations.
    make i18n-compile

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
