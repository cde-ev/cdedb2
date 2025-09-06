#!/usr/bin/env sh

sudo apt install python3-systemd

sudo cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-apitoken.conf /etc/fail2ban/filter.d/cdedb-apitoken.conf
sudo cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-contact.conf /etc/fail2ban/filter.d/cdedb-contact.conf
sudo cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-login.conf /etc/fail2ban/filter.d/cdedb-login.conf
sudo cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-password-reset.conf /etc/fail2ban/filter.d/cdedb-password-reset.conf
sudo cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-sessionkey.conf /etc/fail2ban/filter.d/cdedb-sessionkey.conf
sudo cp /cdedb2/related/auto-build/files/stage3/jail.local /etc/fail2ban/

# sudo systemctl restart fail2ban.service
sudo fail2ban-client reload
