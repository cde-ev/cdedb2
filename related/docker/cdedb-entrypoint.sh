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

    # Create the directory containing the storage manually, to ensure www-data has the proper permissions
    mkdir -p "$(python3 -m cdedb.setup get STORAGE_DIR)"
    chown www-data:www-data "$(python3 -m cdedb.setup get STORAGE_DIR)"
    # now, create the storage itself. Ensure that www-data owns everything.
    sudo -u www-data --preserve-env python3 -m cdedb.setup create-storage
    # populate the storage dir with sample data
    sudo -u www-data --preserve-env python3 -m cdedb.setup populate-storage

    # Create the directory containing the logs manually, to ensure www-data has the proper permissions
    mkdir -p "$(python3 -m cdedb.setup get LOG_DIR)"
    chown www-data:www-data "$(python3 -m cdedb.setup get LOG_DIR)"
    # now, create the directories inside the log. Ensure that www-data owns everything.
    sudo -u www-data --preserve-env python3 -m cdedb.setup create-log

    # Compile the translations
    make i18n-compile

    # create and populate the database
    python3 -m cdedb.setup create-database
    python3 -m cdedb.setup populate-database

    # Touch the firstrun file, so we perform the initialization only once.
    touch /etc/cdedb/container_already_initalized
fi

exec "$@"
