#!/bin/sh
set -e

if [ ! -f /etc/ssl/ldap/ldap.pem ] || [ ! -f /etc/ssl/ldap/ldap.key ]; then
    mkdir -p /etc/ssl/ldap
    openssl req \
        -x509 \
        -newkey rsa:4096 \
        -out /etc/ssl/ldap/ldap.pem \
        -keyout /etc/ssl/ldap/ldap.key \
        -days 365 \
        -nodes \
        -subj "/C=DE/O=CdE e.V./CN=ldap/emailAddress=cdedb@lists.cde-ev.de"
fi

exec "$@"
