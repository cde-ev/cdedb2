#!/bin/bash

echo "Before running this script, the ldap database evolutions must be applied."
read -p "Are you sure to continue? " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    [[ "$0" = "$BASH_SOURCE" ]] && exit 1 || return 1 # handle exits from shell or function but don't exit interactive shell
fi


echo "Install required packages"
sudo apt-get install -y unixodbc odbc-postgresql > /dev/null

echo "Add odbc.ini file"
sudo cp /cdedb2/related/auto-build/files/stage2/odbc.ini /etc/odbc.ini

echo "Add some slapd preset configurations"
sudo debconf-set-selections <<EOF
slapd slapd/internal/adminpw password secret
slapd slapd/internal/generated_adminpw password secret
slapd slapd/password1 password secret
slapd slapd/password2 password secret
slapd slapd/domain string cde-ev.de
slapd shared/organization string CdEDB
EOF

echo "Install slapd"
sudo apt install -y slapd > /dev/null

# remove pre-installed mdb. This uses the same olcSuffix and blocks our sql database
echo
echo "Remove predefined mdb"
sudo rm /etc/ldap/slapd.d/cn=config/olcDatabase=\{1\}mdb.ldif
sudo rm -r /var/lib/ldap
# restart slapd to finish removal of mdb
sudo systemctl restart slapd

echo
echo "Apply our custom ldap configuration"
sudo ldapmodify -Y EXTERNAL -H ldapi:/// -f /cdedb2/sql-ldap.ldif
