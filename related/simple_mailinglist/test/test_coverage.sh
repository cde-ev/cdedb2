#!/bin/sh
#
# Check the code-coverage of unittests.
#
# :Requires:	python-coverage, python3-coverage
#
# :Author:	Roland Koebler <rk@simple-is-better.org>
# :Version:	2018-03-16
#
# :VCS:		$Id$

COVERAGE3=$(command -v python-coverage3 coverage3)
COVERAGE2=$(command -v python-coverage  coverage2)

for f in *.py; do
    echo
    echo "=========================================="
    echo "=== $f"
    echo "------------------------------------------"
    echo "- Python 3: coverage..."
    if [ "$COVERAGE3" == "" ]; then
	echo "NOT INSTALLED."
    else
	$COVERAGE3 run "$f" > /dev/null 2>&1
	$COVERAGE3 report -m
    fi
    echo

    echo "------------------------------------------"
    echo "- Python 2: coverage..."
    if [ "$COVERAGE2" == "" ]; then
	echo "NOT INSTALLED."
    else
	$COVERAGE2 run "$f" > /dev/null 2>&1
	$COVERAGE2 report -m
    fi
    echo

    echo "------------------------------------------"
    echo "- Python 2+3: converage..."
    if [ "$COVERAGE3" == "" ] || [ "$COVERAGE2" == "" ]; then
	echo "NOT INSTALLED."
    else
	$COVERAGE3 run    "$f" > /dev/null 2>&1
	$COVERAGE  run -a "$f" > /dev/null 2>&1
	$COVERAGE3 report -m
    fi
    echo
done
