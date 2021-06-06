#!/bin/bash

cd /cdedb2
git pull
git checkout $2
git pull
make -B tests/ancillary_files/sample_data.sql
./bin/check.py 2> >(tee -a /tmp/output-check.txt >&2)
echo "CONDENSED REPORT:"
grep -E '^(ERROR|FAIL):' /tmp/output-check.txt
echo "BRANCH: $2"
sudo shutdown -h now
