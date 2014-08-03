#!/bin/bash
BINDIR=/home/cdedb/cdedb2/bin/
LOGFILE=$(mktemp)
MAILTO=cdedb@lists.cde-ev.de

$BINDIR/cdedb-autobuild-stage3.sh &> $LOGFILE
RETVAL=$?

if [[ $RETVAL -eq 0 ]]; then
	rm -f $LOGFILE
	exit 0
fi;
if [[ $RETVAL -eq 1 ]]; then
	cat $LOGFILE | mail -s "cdedb2-auto-build: neue Version" $MAILTO
	rm -f $LOGFILE
	exit 0
fi;

cat $LOGFILE | mail -s "cdedb2: auto-build failure" $MAILTO

rm -f $LOGFILE
exit $RETVAL
