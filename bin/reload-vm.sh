#!/bin/bash
echo "Reloading backends"
BACKENDS="session core cde event"
sudo sv restart $BACKENDS
echo "Reloading frontend"
touch /cdedb2/wsgi/cdedb.wsgi
echo "Done"
