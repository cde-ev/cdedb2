# copy the systemd service file to the right place
cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/

# TODO enable on Dev VMs
# cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/cde-ldap-test.service
# sed -i -r -e "s|Environment=CDEDB_CONFIGPATH=/etc/cdedb/config.py|Environment=CDEDB_CONFIGPATH=/cdedb2/tests/config/test_ldap.py\nEnvironment=PYTHONPATH=/cdedb2/|g" /etc/systemd/system/cde-ldap-test.service
# sed -i -r -e "s|ReadWritePaths=/var/log/cdedb|ReadWritePaths=/tmp|g" /etc/systemd/system/cde-ldap-test.service
# sed -i -r -e "s|User=www-cde|User=cdedb|g" /etc/systemd/system/cde-ldap-test.service
# sed -i -r -e "s|Group=www-cde|Group=cdedb|g" /etc/systemd/system/cde-ldap-test.service

sudo systemctl daemon-reload
sudo systemctl restart cde-ldap
