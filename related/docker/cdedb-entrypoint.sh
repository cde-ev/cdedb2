#!/bin/sh

if [ ! -d /etc/ssl/apache2 ]; then
    # If the apache2 directory does not exist we have to create it and add a certificate.
    mkdir /etc/ssl/apache2
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

    # create a world-readable version of the secrets config with no content.
    # This needs to be adjusted for productive use.
    touch "$(python3 -m cdedb.setup secrets-configpath)"
    chown www-data:www-data "$(python3 -m cdedb.setup secrets-configpath)"
    chmod 644 "$(python3 -m cdedb.setup secrets-configpath)"

    # Create and populate the storage and log dirs
    python3 -m cdedb.setup create-storage --owner www-data
    python3 -m cdedb.setup populate-storage --owner www-data
    python3 -m cdedb.setup create-log --owner www-data

    # Compile the translations
    make i18n-compile

    # create and populate the database
    python3 -m cdedb.setup create-database
    python3 -m cdedb.setup populate-database

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
