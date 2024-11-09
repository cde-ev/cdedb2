# stop openldap's slapd
sudo systemctl stop slapd

# copy the (fixed) cde-ldap systemd file ...
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/

# ... and create the new cde-ldap-test systemd file
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/cde-ldap-test.service
sudo sed -i -r -e "s|Environment=CDEDB_CONFIGPATH=/etc/cdedb/config.py|Environment=CDEDB_CONFIGPATH=/cdedb2/tests/config/test_ldap.py\nEnvironment=PYTHONPATH=/cdedb2/|g" /etc/systemd/system/cde-ldap-test.service

# then, reload systemd and enable the cde-ldap service
sudo systemctl daemon-reload
sudo systemctl enable cde-ldap.service
sudo systemctl restart cde-ldap.service
