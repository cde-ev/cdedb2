#!/bin/sh
set -e

if [ ! -f /etc/cdedb/ldap/ldap.pem ] || [ ! -f /etc/cdedb/ldap/ldap.key ]; then
    mkdir -p /etc/cdedb/ldap
    openssl req \
        -x509 \
        -newkey rsa:4096 \
        -out /etc/cdedb/ldap/ldap.pem \
        -keyout /etc/cdedb/ldap/ldap.key \
        -days 365 \
        -nodes \
        -subj "/C=DE/O=CdE e.V./CN=ldap/emailAddress=cdedb@lists.cde-ev.de"
fi

exec "$@"
