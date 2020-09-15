#!/bin/bash

export TESTPREPARATION=manual
cd /cdedb2
git pull &> /dev/null

# old version
echo "Checkout $2"
git checkout $2 &> /dev/null
git pull &> /dev/null
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
make -B test/ancillary_files/sample_data.sql &> /dev/null
make sample-data &> /dev/null
make sample-data-test &> /dev/null
sudo -u postgres psql -U postgres -d cdb_test \
     -c "SELECT (table_schema || '.' || table_name) AS full_name
         FROM information_schema.tables
         WHERE table_schema != 'information_schema'
               AND table_schema != 'pg_catalog'
         ORDER BY table_schema, table_name" \
    | sort > /tmp/alltables.txt
for table in $(cat /tmp/alltables.txt)
do
    sudo -u postgres psql -U postgres -d cdb_test -c "\d $table" \
        | sort > /tmp/spec-old-$table.txt
done;

# new version
echo "Checkout $3"
git checkout $3 &> /dev/null
git pull &> /dev/null
make -B test/ancillary_files/sample_data.sql &> /dev/null
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt \
     > /tmp/todoevolutions.txt
echo "" > /tmp/output-evolution.txt
for evolution in $(cat /tmp/todoevolutions.txt); do
    echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
    sudo -u postgres psql -U postgres -d cdb_test \
         -f cdedb/database/evolutions/$evolution \
         2>&1 | tee -a /tmp/output-evolution.txt
done
make i18n-compile
make sample-data-test-shallow
sudo -u postgres psql -U postgres -d cdb_test \
     -c "SELECT (table_schema || '.' || table_name) AS full_name
         FROM information_schema.tables
         WHERE table_schema != 'information_schema'
               AND table_schema != 'pg_catalog'
         ORDER BY table_schema, table_name" \
    | sort > /tmp/alltables.txt
for table in $(cat /tmp/alltables.txt)
do
    sudo -u postgres psql -U postgres -d cdb_test -c "\d $table" \
        | sort > /tmp/spec-new-$table.txt
done;


# perform check
./bin/check.sh 2> >(tee -a /tmp/output-check.txt >&2)
echo ""
echo "DATABASE COMPARISON:"
for table in $(cat /tmp/alltables.txt)
do
    echo "Comparing spec for $table"
    diff -u /tmp/spec-old-$table.txt /tmp/spec-new-$table.txt
done;
echo ""
echo "CONDENSED REPORT:"
grep -E '^(ERROR|FAIL):' /tmp/output-check.txt
echo ""
echo "EVOLUTIONS:"
cat /tmp/output-evolution.txt
echo ""
echo "OLD: $2 NEW: $3"
sudo shutdown -h now
