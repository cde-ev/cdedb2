#!/bin/bash
BINDIR=/home/cdedb/cdedb2/bin/
LOGFILE=$(mktemp)
MAILTO=cdedb@lists.cde-ev.de

COUNT=`ps aux | grep invoke-autobuild.sh | wc -l`
if [ $COUNT -gt 4 ]; then
    echo "Already running $COUNT processes." | mail -s "cdedb2: auto-build abort" $MAILTO
    exit 42
fi

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
