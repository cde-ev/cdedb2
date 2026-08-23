#!/bin/bash
#
# This is a script to filter .po files before checkin.
#
# It removes all lines starting with '#:' to ignore changes to line numbers
# where translatable strings are used.
#
# To set this up, add the following to your .git/config file:
#
#   [filter "pofilter"]
#       clean = i18n/git-filter-po-clean.sh
#

sed "/^#:/d" "$@"
