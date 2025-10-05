#!/bin/bash

if [ -f /PRODUCTIONVM ]; then
    echo "Refusing to change service in production!"
    exit 0
fi

sudo cp related/auto-build/files/stage3/cdedb-app.service /etc/systemd/system/
sudo systemctl daemon-reload
