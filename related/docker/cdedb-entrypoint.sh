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
    # TODO check whether it is sensible to lower privileges to cdedb user in general

    # Create the storage dir itself. Ensure that www-data owns everything.
    python3 -m cdedb filesystem storage create --owner www-data
    # Populate the storage dir with sample data
    python3 -m cdedb filesystem storage populate --owner www-data

    # Create the log dir itself. Ensure that www-data owns everything.
    python3 -m cdedb filesystem log create --owner www-data

    # Compile the translations
    make i18n-compile

    # create and populate the database
    python3 -m cdedb db create-users
    python3 -m cdedb db create
    python3 -m cdedb db populate

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
