#!/bin/sh
#
# Run all unittests.
#
# :Author:	Roland Koebler <rk@simple-is-better.org>
# :Version:	2018-03-16
#
# :VCS:		$Id$

for f in *.py; do
    echo
    echo "=========================================="
    echo "=== $f"
    echo "------------------------------------------"
    echo "- Python 3: unittest..."
    python3 "$f"
    if [ "$?" != "0" ]; then
	echo "FAILED."
	exit
    fi
    echo

    echo "------------------------------------------"
    echo "- Python 2: unittest..."
    python2 "$f"
    if [ "$?" != "0" ]; then
	echo "FAILED."
	exit
    fi
    echo
done

