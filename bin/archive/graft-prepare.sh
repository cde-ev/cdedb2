#!/bin/bash

sudo -u postgres psql -f /cdedb2/cdedb/database/graft-prepare.sql
sudo -u postgres psql -d cdedbxy -f /cdedb2/cdedbv1.sql

