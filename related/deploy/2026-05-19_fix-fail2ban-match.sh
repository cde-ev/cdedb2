#!/usr/bin/env sh

cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-apitoken.conf /etc/fail2ban/filter.d/cdedb-apitoken.conf
cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-contact.conf /etc/fail2ban/filter.d/cdedb-contact.conf
cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-login.conf /etc/fail2ban/filter.d/cdedb-login.conf
cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-password-reset.conf /etc/fail2ban/filter.d/cdedb-password-reset.conf
cp /cdedb2/related/auto-build/files/stage3/fail2ban-filter-cdedb-sessionkey.conf /etc/fail2ban/filter.d/cdedb-sessionkey.conf
cp /cdedb2/related/auto-build/files/stage3/jail.local /etc/fail2ban/

systemctl reload fail2ban.service
