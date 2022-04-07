#!/bin/bash
# Event keeper apache deployment script.
sudo a2enmod ldap
sudo a2enmod authnz_ldap
sudo cdedb-update.sh

# Then run make ldap-update
# Then adjust /etc/apache2/sites-available/cdedb-site.conf according to /cdedb2/auto-build/files/stage3/cdedb-site.conf
# Then run cdedb-update.sh
