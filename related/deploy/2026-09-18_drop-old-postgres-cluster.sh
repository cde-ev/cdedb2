#!/usr/bin/env sh

read -p "Remove /var/lib/postgresql/13? (y/n) " choice
if [ "$choice" != "y" ]; then
  echo Aborting
  exit 1
fi

sudo rm -r /var/lib/postgresql/13
