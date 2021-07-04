#!/bin/sh
# We can only perform some initialization after the normal build process.
# Those steps are exactly the ones which require connection to the sql db.

if [ ! -e /var/lib/ldap/container_already_initalized ]; then
    # Start slapd in the background (in foreground mode with -d 0 to prevent forking)
    # with ldapi:// (unix socket) to allow for simple authentication with ldapmodify.
    slapd -d -1 -h ldapi:// &
    # Wait for slapd to come up.
    sleep 5
    # Run ldapmodify to initialize the ldap-sql backend and config.
    ldapmodify -Y EXTERNAL -H ldapi:// -f /tmp/sql-ldap.ldif
    # Stop the slapd process we started first.
    kill -INT $(cat /run/slapd/slapd.pid)

    # Touch the firstrun file so that we only perform the above once.
    touch /var/lib/ldap/container_already_initalized
fi

exec $@
