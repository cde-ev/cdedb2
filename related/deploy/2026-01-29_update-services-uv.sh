#!/bin/bash

if [ -f /PRODUCTIONVM ]; then
    echo "Refusing to change service in production!"
    exit 0
fi

echo "Replacing services"
sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app.service /etc/systemd/system/
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/cde-ldap-test.service
sudo systemctl daemon-reload
echo "Services replaced and systemctl reloaded."

if [ ! -d /home/www-cde ]; then
    echo "Creating home directory for www-cde user."
    sudo mkdir /home/www-cde
    sudo chown -R www-cde:www-cde /home/www-cde
    echo "Stopping services cdedb-app cde-ldap and cde-ldap-test."
    sudo systemctl stop cdedb-app cde-ldap cde-ldap-test
    sudo usermod -d /home/www-cde www-cde
    echo "Restarting cdedb-app. This will setup the venv for the services. This may take a minute or two."
    sudo systemctl start cdedb-app
    echo "Restarted cdedb-app. Make sure to restart cde-ldap and cde-ldap-test yourself if necessary."
fi
