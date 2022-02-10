#!/bin/bash
# Event keeper deployment script.
cd /etc/apache2/mods-enabled
sudo ln -s ../mods-available/ldap.conf
sudo ln -s ../mods-available/ldap.load
sudo ln -s ../mods-available/authnz_ldap.load
sudo cdedb-update.sh

# Then run as root SCRIPT_DRY_RUN="" python3 /cdedb2/ldap/update-ldap.py
# Then adjust /etc/apache2/sites-available/cdedb-site.conf according to /cdedb2/auto-build/files/stage3/cdedb-site.conf
# Then run cdedb-update.sh
