#!/bin/bash
#
# Three-way merge driver for PO files
#
# It uses the gettext utils (msgcat, msggrep, msgmerge, msguniq) to correctly process
# the .po and .pot files. These tools are typically contained in the `gettext` package
# of Linux distributions.
#
# To set this up, add the following to your .git/config file:
#
#   [merge "pomerge"]
#     name = Gettext merge driver
#     driver = i18n/get-merge-po.sh %O %A %B
#
# It is recommended to delete all duplicte message defintions before trying to
# merge branches.
#
# Taken from https://github.com/mezis/git-whistles/blob/master/libexec/git-merge-po.sh
# and adapted to remove obsolete strings and sort by file.
#
set -e
IFS=
# failure handler
on_error() {
  local parent_lineno="$1"
  local message="$3"
  local code="$2"
  if [[ -n "$message" ]] ; then
    echo "Error on or near line ${parent_lineno}: ${message}; Code ${code}"
  else
    echo "Error on or near line ${parent_lineno}; Code ${code}"
  fi
  exit 255
}
trap 'on_error ${LINENO} $?' ERR

# given a file, find the path that matches its contents
show_file() {
  hash=`git hash-object "${1}"`
  git ls-tree -r HEAD | fgrep "$hash" | cut -b54-
}

# wraps msgmerge with default options
function m_msgmerge() {
  msgmerge --force-po --quiet --no-fuzzy-matching $@
}

# wraps msgcat with default options
function m_msgcat() {
  msgcat --force-po $@
}


# removes the "graveyard strings" from the input
function strip_graveyard() {
  sed -e '/^#~/d'
}

# select messages with a conflict marker
# pass -v to inverse selection
function grep_conflicts() {
  msggrep $@ --msgstr -F -e '#-#-#-#-#' -
}

# select messages from $1 that are also in $2 but whose contents have changed
function extract_changes() {
  msgcat -o - $1 $2 \
    | grep_conflicts \
    | m_msgmerge -o - $1 - \
    | strip_graveyard
}


BASE=$1
LOCAL=$2
REMOTE=$3
OUTPUT=$LOCAL
TEMP=$(mktemp)
# the custom tempfile naming whyever does not work in our CI
# TEMP=`mktemp /tmp/merge-po.XXXX`

echo "Using custom PO merge driver (`show_file ${LOCAL}`; $TEMP)"

# Extract the PO header from the current branch (top of file until first empty line)
sed -e '/^$/q' < $LOCAL > ${TEMP}.header

# clean input files
msguniq --force-po -o ${TEMP}.base ${BASE}
msguniq --force-po -o ${TEMP}.local ${LOCAL}
msguniq --force-po -o ${TEMP}.remote ${REMOTE}

# messages changed on local
extract_changes ${TEMP}.local ${TEMP}.base > ${TEMP}.local-changes

# messages changed on remote
extract_changes ${TEMP}.remote ${TEMP}.base > ${TEMP}.remote-changes

# unchanged messages
m_msgcat -o - ${TEMP}.base ${TEMP}.local ${TEMP}.remote \
  | grep_conflicts -v \
  > ${TEMP}.unchanged

# the big merge
m_msgcat -o ${TEMP}.merge1 ${TEMP}.unchanged ${TEMP}.local-changes ${TEMP}.remote-changes

# create a template to filter messages actually needed (those on local and remote)
# and remove messages that became obsolete
m_msgcat -o - ${TEMP}.local ${TEMP}.remote \
  | m_msgmerge -o - ${TEMP}.merge1 - \
  | msgattrib --no-obsolete -o ${TEMP}.merge2 -

# final merge, adds saved header
m_msgcat --sort-by-file -o ${TEMP}.merge3 --use-first ${TEMP}.header ${TEMP}.merge2

# produce output file (overwrites input LOCAL file)
cat ${TEMP}.merge3 > $OUTPUT

# check for conflicts
if grep -q '#-#-#-#-#' $OUTPUT ; then
  echo "Conflict(s) detected"
  echo "   between ${TEMP}.local and ${TEMP}.remote"
  exit 1
fi
rm -f ${TEMP}*
exit 0

