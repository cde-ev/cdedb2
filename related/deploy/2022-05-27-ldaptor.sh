# Stop openldap's slapd daemon
sudo systemctl stop slapd

# Install python packages required for ldaptor
sudo python3 -m pip install --no-cache-dir \
    ldaptor==21.2.0 \
    aiopg==1.3.3 \
    async_timeout==4.0.2

# Add the new systemd service file ...
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/
# ... and start it
sudo systemctl start cde-ldap
