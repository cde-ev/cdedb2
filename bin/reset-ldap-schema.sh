#!/bin/bash

echo "This is basically impossible, so use this at your own risk."
echo "We now chicken out. The code below is mainly for documentation purposes."
exit 0

#
# First delete personas
#

echo 'ou=personas,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true
echo 'ou=personas-test,dc=cde-ev,dc=de' | ldapdelete -c -r -x -D `cat .ldap_rootdn` -y ${LDAP_PASSWORDFILE} || true

#
# Second delete schema
#

sudo systemctl stop slapd
sudo rm "/etc/ldap/slapd.d/cn=config/cn=schema/cn=*cdepersona.ldif"
sudo systemctl start slapd

#
# Third repopulate
# Taken from auto-build
#

sudo ldapmodify -Y EXTERNAL -H ldapi:/// -f /cdedb2/related/auto-build/files/stage3/init.ldif
TMPDIR=`mktemp -d`
slaptest -f /cdedb2/related/auto-build/files/stage3/temp_ldap.conf -F $TMPDIR
# stupid LDAP needs manual fixing
sed -n -i -e '/structuralObjectClass: olcSchemaConfig/q;p' "$TMPDIR/cn=config/cn=schema/cn="*"cdepersona.ldif"
sed -i -e 's/^dn: cn={[0-9]\+}cdepersona/dn: cn=cdepersona,cn=schema,cn=config/' "$TMPDIR/cn=config/cn=schema/cn="*"cdepersona.ldif"
sed -i -e 's/^cn: {[0-9]\+}cdepersona/cn: cdepersona/' "$TMPDIR/cn=config/cn=schema/cn="*"cdepersona.ldif"
sudo ldapadd -Y EXTERNAL -H ldapi:/// -f "$TMPDIR/cn=config/cn=schema/cn="*"cdepersona.ldif"
rm -rf $TMPDIR
cd /cdedb2 && make ldap
