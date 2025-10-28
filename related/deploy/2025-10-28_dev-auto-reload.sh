#!/bin/bash

if [ -f /PRODUCTIONVM ]; then
    echo "Refusing to install reload service in production!"
    exit 0
fi

sudo cp related/auto-build/files/stage3/cdedb-app-restart.{service,path} /etc/systemd/system/
sudo systemctl enable --now cdedb-app-restart.path
