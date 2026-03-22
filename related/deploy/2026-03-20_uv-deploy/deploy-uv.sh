#!/bin/bash

echo "Installing python package build requirements"
sudo apt-get install g++ pkg-config graphviz libmagic1 python3-dev libicu-dev libsystemd-dev

echo "Installing uv"
sudo python3 -m pip install --break-system-packages uv
echo ""

echo "Setting up uv shell-completion and python directory for root"
sudo cat /cdedb2/related/deploy/2026-03-20_uv-deploy/root-bashrc | sudo tee /root/.bashrc --append
echo ""

echo "Creating global uv config"
sudo mkdir -p /etc/uv
sudo cp /cdedb2/related/deploy/2026-03-20_uv-deploy/etc-uv.toml /etc/uv/uv.toml
echo ""

echo "Creating root uv config"
sudo mkdir -p /root/.config/uv
sudo cp /cdedb2/related/deploy/2026-03-20_uv-deploy/root-uv.toml /root/.config/uv/uv.toml
echo ""

if [ -f /PRODUCTIONVM ]; then
    echo "Replacing services"
    sudo cp /cdedb2/related/deploy/2026-03-20_uv-deploy/cdedb-app.service /etc/systemd/system/
    sudo cp /cdedb2/related/deploy/2026-03-20_uv-deploy/cde-ldap.service /etc/systemd/system/
    sudo systemctl daemon-reload
    echo "Services replaced and systemctl reloaded."
else
    echo "Setting up dev venv and dev services. This may take a minute or two."
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app.service /etc/systemd/system/
    sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app-restart.path /etc/systemd/system/
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app-restart.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now cdedb-app-restart.path
    sudo rm -r /cdedb2/.venv
    make -C /cdedb2 venv
fi

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
