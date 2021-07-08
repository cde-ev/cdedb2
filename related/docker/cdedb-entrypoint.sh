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

if ! python3 bin/execute_sql_script.py -f /dev/null 2> /dev/null; then
    # Apparently we cannot connect with the cdb user so we assume no sample-data is present.
    make sample-data
fi

exec "$@"
