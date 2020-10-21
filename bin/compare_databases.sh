#!/bin/bash

# Takes the base commit as the first and the target commit as the second argument.
# This does not modify the `cdb` database, but the `cdb_text` database.

export TESTPREPARATION=manual
cd /cdedb2

# old version
echo "Checkout $1"
git checkout $1 &> /dev/null
git pull &> /dev/null
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
make -B test/ancillary_files/sample_data.sql &> /dev/null
make sql-test &> /dev/null

# new version
echo "Checkout $2"
git checkout $2 &> /dev/null
git pull &> /dev/null
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
echo "Compiling list of evolutions to apply."
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt \
     > /tmp/todoevolutions.txt
echo ""
cat /tmp/todoevolutions.txt
echo ""
echo "" > /tmp/output-evolution.txt
for evolution in $(cat /tmp/todoevolutions.txt); do
    echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
    sudo -u postgres psql -U postgres -d cdb_test \
         -f cdedb/database/evolutions/$evolution
done
echo "Creating database description."
sudo -u postgres psql -U postgres -d cdb_test \
     -f bin/describe_database.sql > /tmp/old-description.txt
bin/normalize_database_description.py /tmp/old-description.txt
echo "Resetting database."
make -B test/ancillary_files/sample_data.sql &> /dev/null
make sql-test &> /dev/null
echo "Creating database description again."
sudo -u postgres psql -U postgres -d cdb_test \
     -f bin/describe_database.sql > /tmp/new-description.txt
bin/normalize_database_description.py /tmp/new-description.txt

# perform check
echo ""
echo "DATABASE COMPARISON (this should be empty):"
comm -3 <(sort /tmp/old-description.txt) <(sort /tmp/new-description.txt)
echo ""
echo "EVOLUTIONS:"
cat /tmp/output-evolution.txt
echo ""
echo "OLD: $1 NEW: $2"
