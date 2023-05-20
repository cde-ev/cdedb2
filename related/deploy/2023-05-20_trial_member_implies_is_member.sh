#!/bin/bash
sudo -u cdb psql -U cdb -d cdb -f /cdedb2/cdedb/database/evolutions/2023-05-20_trial_member_implies_is_member.sql
