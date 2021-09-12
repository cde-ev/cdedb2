#!/bin/bash


EXENAME=$(basename $0)
DATABASE_NAME = cdb_test_evolution

OLDREVISION=$1
NEWREVISION=$2


export TESTPREPARATION=manual
export TESTDATABASENAME=$DATABASE_NAME
cd /cdedb2

# old revision
echo "Checkout $OLDREVISION"
git checkout $OLDREVISION
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
make -B tests/ancillary_files/sample_data.sql &> /dev/null
make sql-test &> /dev/null

# new revision
echo "Checkout $NEWREVISION"
git checkout $NEWREVISION
git pull
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt \
     > /tmp/todoevolutions.txt
truncate -s0 /tmp/output-evolution.txt
for evolution in $(cat /tmp/todoevolutions.txt); do
    echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
    sudo -u cdb psql -U cdb -d $DATABASE_NAME \
         -f cdedb/database/evolutions/$evolution \
         2>&1 | tee -a /tmp/output-evolution.txt
done

# evolved db
echo "Creating database description."
sudo -u postgres psql -U postgres -d $DATABASE_NAME \
     -f bin/describe_database.sql > /tmp/evolved-description.txt
bin/normalize_database_description.py /tmp/evolved-description.txt

make i18n-compile
make -B tests/ancillary_files/sample_data.sql &> /dev/null

# new db
echo "Resetting and creating database description again."
make sql-test &> /dev/null
sudo -u postgres psql -U postgres -d cdb_test \
     -f bin/describe_database.sql > /tmp/pristine-description.txt
bin/normalize_database_description.py /tmp/pristine-description.txt

# perform check
echo ""
echo "DATABASE COMPARISON (this should be empty):"
comm -3 <(sort /tmp/evolved-description.txt) \
     <(sort /tmp/pristine-description.txt)
echo ""
echo "EVOLUTION OUTPUT:"
cat /tmp/output-evolution.txt
echo ""
echo "OLD: $OLDREVISION NEW: $NEWREVISION"
