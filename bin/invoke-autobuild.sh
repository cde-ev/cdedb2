#!/bin/bash
BINDIR=/home/cdedb/cdedb2/bin/
LOCKFILE=/home/cdedb/cdedb2-autobuild.lock
LOGFILE=$(mktemp)
MAILTO=cdedb@lists.cde-ev.de

echo "Autobuild started at $(date)" > $LOGFILE
timeout -k 5s 23h flock -n -E 123 $LOCKFILE \
        $BINDIR/cdedb-autobuild-stage3.sh &>> $LOGFILE
RETVAL=$?
echo "Autobuild finished at $(date)" >> $LOGFILE

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
if [[ $RETVAL -eq 123 ]]; then
    mail -s "cdedb2-auto-build: abort" $MAILTO
    rm -f $LOGFILE
    exit 0
fi;
if [[ $RETVAL -eq 124 ]]; then
    mail -s "cdedb2-auto-build: timeout terminated" $MAILTO
    rm -f $LOGFILE
    exit 0
fi;
if [[ $RETVAL -eq 137 ]]; then
    mail -s "cdedb2-auto-build: timeout killed" $MAILTO
    rm -f $LOGFILE
    exit 0
fi;

echo "Autobuild exited with return code $RETVAL" >> $LOGFILE
cat $LOGFILE | mail -s "cdedb2: auto-build failure" $MAILTO

rm -f $LOGFILE
exit $RETVAL
