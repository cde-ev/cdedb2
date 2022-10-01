#!/bin/sh
set -e

if [ ! -f /etc/ldap/certs/ldap.pem ] || [ ! -f /etc/ldap/certs/ldap.key ]; then
    mkdir -p /etc/ldap/certs
    openssl req \
        -x509 \
        -newkey rsa:4096 \
        -out /etc/ldap/certs/ldap.pem \
        -keyout /etc/ldap/certs/ldap.key \
        -days 365 \
        -nodes \
        -subj "/C=DE/O=CdE e.V./CN=ldap/emailAddress=cdedb@lists.cde-ev.de"
fi

exec "$@"
