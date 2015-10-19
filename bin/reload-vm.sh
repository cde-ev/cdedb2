#!/bin/bash
echo "Reloading backends"
BACKENDS="session core cde event"
sudo sv restart $BACKENDS # FIXME fails
echo "Reloading frontend"
touch /cdedb2/wsgi/cdedb.wsgi
echo "Done"
