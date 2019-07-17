#!/bin/bash
BINDIR=/home/cdedb/cdedb2/bin/
LOCKFILE=/home/cdedb/cdedb2-autobuild.lock
LOGFILE=$(mktemp)
MAILTO=cdedb@lists.cde-ev.de

flock -n -E -42 $LOCKFILE $BINDIR/cdedb-autobuild-stage3.sh &> $LOGFILE
RETVAL=$?

if [[ $RETVAL -eq 0 ]]; then
    # autobuild is up to date
    rm -f $LOGFILE
    exit 0
fi;
if [[ $RETVAL -eq 1 ]]; then
    cat $LOGFILE | mail -s "cdedb2-auto-build: neue Version" $MAILTO
    rm -f $LOGFILE
    exit 0
fi;
if [[ $RETVAL -eq -42 ]]; then
    mail -s "cdedb2-auto-build: abort" $MAILTO
    rm -f $LOGFILE
    exit 0
fi;

echo "Autobuild exited with return code $RETVAL" >> $LOGFILE
cat $LOGFILE | mail -s "cdedb2: auto-build failure" $MAILTO

rm -f $LOGFILE
exit $RETVAL
