#!/bin/bash

echo "Installing python package build requirements"
sudo apt-get install g++ pkg-config python3-dev libicu-dev graphviz libmagic1 libsystemd-dev

echo "Installing uv"
sudo python3 -m pip install --break-system-packages uv
echo ""

echo "Setting up uv shell-completion and python directory for root"
sudo cat /cdedb2/related/auto-build/files/stage2/root-bashrc | sudo tee /root/.bashrc --append
echo ""

echo "Creating global uv config"
sudo mkdir -p /etc/uv
sudo cp /cdedb2/related/auto-build/files/stage2/etc-uv.toml /etc/uv/uv.toml
echo ""

echo "Creating root uv config"
sudo mkdir -p /root/.config/uv
sudo cp /cdedb2/related/auto-build/files/stage2/root-uv.toml /root/.config/uv/uv.toml
echo ""

if [ ! -d /home/www-cde ]; then
    echo "Creating home directory for www-cde user."
    sudo mkdir /home/www-cde
    sudo chown -R www-cde:www-cde /home/www-cde
    echo "Stopping services cdedb-app cde-ldap and cde-ldap-test."
    sudo systemctl stop cdedb-app cde-ldap cde-ldap-test
    sudo usermod -d /home/www-cde www-cde
    echo "Make sure to restart cde-ldap and cde-ldap-test yourself if necessary."
else
    if [ -d /home/www-cde/.venv ]; then
        sudo rm -r /home/www-cde/.venv
        sudo make -C /cdedb2 www-cde-venv
    fi
fi

echo "Replacing services"
sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app.service /etc/systemd/system/
sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/
sudo systemctl daemon-reload
echo "Services replaced and systemctl reloaded."

if [ ! -f /PRODUCTIONVM ]; then
    echo "Setting up dev venv and dev services."
    sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap.service /etc/systemd/system/cde-ldap-test.service
    sudo mkdir /etc/systemd/system/cdedb-app.service.d/
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app-dev.conf /etc/systemd/system/cdedb-app.service.d/50-dev-override.conf
    sudo mkdir /etc/systemd/system/cde-ldap.service.d/
    sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap-dev.conf /etc/systemd/system/cde-ldap.service.d/50-dev-override.conf
    sudo mkdir /etc/systemd/system/cde-ldap-test.service.d/
    sudo cp /cdedb2/related/auto-build/files/stage3/cde-ldap-test.conf /etc/systemd/system/cde-ldap-test.service.d/50-test-override.conf
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app-restart.path /etc/systemd/system/
    sudo cp /cdedb2/related/auto-build/files/stage3/cdedb-app-restart.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now cdedb-app-restart.path
    sudo rm -r /cdedb2/.venv
fi

echo "Setting up virtual environments. This may take a minute or two."
sudo make -C /cdedb2 venv www-cde-venv
