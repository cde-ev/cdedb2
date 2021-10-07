#!/bin/sh
# We can only perform some initialization after the normal build process.
# Those steps are exactly the ones which require connection to the sql db.
# Furthermore we adjust some values in the config depending on environment variables.
set -x

if [ ! -e /var/lib/ldap/container_already_initalized ]; then
    # we assume this is the first start and therefore also the db is uninitialized
    # consequently we give the app container time to create the sample-data
    sleep 20

    # the duas must be manually added by applying ldap/output/add-duas.sql
    # in dev and test instances, they are included in the sample-data.

    # remove pre-installed mdb. This uses the same olcSuffix and blocks our sql database
    rm /etc/ldap/slapd.d/cn=config/olcDatabase=\{1\}mdb.ldif

    # TODO replace the following hacks with a proper config during rendering the templates.
    # Replace localhost with cdb as that is where the db is accesible by default.
    sed -i "s/localhost/${DATABASE_HOST:-cdb}/" /etc/odbc.ini /app/config-ldap.ldif
    sed -i "s/localhost/${DATABASE_HOST:-cdb}/" /etc/odbc.ini /app/cdedb-ldap.ldif

    # This is required for testing where the database name differs.
    if [ ! -z "${DATABASE_NAME}" ]; then
        sed -i -r "s/\[cdb\]/[${DATABASE_NAME}]/" /etc/odbc.ini
        sed -i -r "s/(Database\s*=\s*)cdb/\1${DATABASE_NAME}/" /etc/odbc.ini
        sed -i -r "s/(olcDbName:\s*)cdb/\1${DATABASE_NAME}/" /app/config-ldap.ldif
        sed -i -r "s/(olcDbName:\s*)cdb/\1${DATABASE_NAME}/" /app/cdedb-ldap.ldif
    fi

    # Start slapd in the background (in foreground mode with -d 0 to prevent forking)
    # with ldapi:// (unix socket) to allow for simple authentication with ldapmodify.
    slapd -d 0 -h ldapi:// &
    # Wait for slapd to come up.
    sleep 5
    # Run ldapmodify to initialize the ldap-sql backend and config.
    ldapmodify -Y EXTERNAL -H ldapi:// -f /app/config-ldap.ldif
    ldapmodify -Y EXTERNAL -H ldapi:// -f /app/cdedb-ldap.ldif
    # Stop the slapd process we started first.
    kill -INT "$(cat /run/slapd/slapd.pid)"

    # Touch the firstrun file so that we only perform the above once.
    touch /var/lib/ldap/container_already_initalized
fi

exec "$@"
