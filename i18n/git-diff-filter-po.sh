#!/bin/bash
#
# This is a script to filter .po files for diffing.
#
# It ignores all lines starting with '#:' to ignore changes to line numbers
# where translatable strings are used.
#
# To set this up, add the following to your .git/config file:
#
#   [diff "podiff"]
#     textconv = i18n/git-diff-filter-po.sh
#
# Then add the following line to your .git/info/attributes file:
#
#   *.po diff=podiff
#   *.pot diff=podiff
#
# taken from: https://gist.github.com/stephenharris/3c3792568494b2a7cf48

grep -vE '^#:|POT-Creation-Date' $1
