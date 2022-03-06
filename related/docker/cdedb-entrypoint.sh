#!/bin/sh
set -e

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

    # Create the directory containing the storage directory manually, to ensure www-data has the proper permissions
    mkdir -p "$(python3 -m cdedb_setup config get STORAGE_DIR)"
    chown www-data:www-data "$(python3 -m cdedb_setup config get STORAGE_DIR)"
    # now, create the storage directory itself. Ensure that www-data owns everything.
    python3 -m cdedb_setup filesystem storage create --user www-data
    # populate the storage dir with sample data
    python3 -m cdedb_setup filesystem storage populate --user www-data

    # Create the directory containing the logs directory manually, to ensure www-data has the proper permissions
    mkdir -p "$(python3 -m cdedb_setup config get LOG_DIR)"
    chown www-data:www-data "$(python3 -m cdedb_setup config get LOG_DIR)"
    # now, create the log directory itself. Ensure that www-data owns everything.
    python3 -m cdedb_setup filesystem log create --user www-data

    # Compile the translations
    make i18n-compile

    # create and populate the database
    python3 -m cdedb_setup database create-users
    python3 -m cdedb_setup database create
    python3 -m cdedb_setup database populate

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
