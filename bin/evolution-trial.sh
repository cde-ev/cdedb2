#!/bin/bash


DATABASE_NAME=cdb_test

OLDREVISION=$1
NEWREVISION=$2


cd /cdedb2

# old revision
echo ""
echo "Checkout $OLDREVISION"
git checkout $OLDREVISION
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
# TODO replace make calls with
# python3 -m cdedb_setup dev compile-sample-data
# python3 -m cdedb_setup database create
# python3 -m cdedb_setup database populate
make -B tests/ancillary_files/sample_data.sql &> /dev/null
make sql DATABASE_NAME=$DATABASE_NAME > /dev/null

# new revision
echo ""
echo "Checkout $NEWREVISION"
git checkout $NEWREVISION

# determine evolutions to apply.
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt \
     > /tmp/todoevolutions.txt

# apply all evolutions and gather the output.
truncate -s0 /tmp/output-evolution.txt
for evolution in $(cat /tmp/todoevolutions.txt); do
    if [[ $evolution == *.sql ]]; then
        echo ""
        echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
        python3 -m cdedb_setup dev execute-sql-script -v \
             -f cdedb/database/evolutions/$evolution \
             2>&1 | tee -a /tmp/output-evolution.txt
    fi
    if [[ $evolution == *.py ]]; then
        echo ""
        echo "Run migration script $evolution" | tee -a /tmp/output-evolution.txt
        sudo -u www-data \
            EVOLUTION_TRIAL_OVERRIDE_DBNAME=$DATABASE_NAME \
            EVOLUTION_TRIAL_OVERRIDE_DRY_RUN='' \
            EVOLUTION_TRIAL_OVERRIDE_PERSONA_ID=1 \
            python3 cdedb/database/evolutions/$evolution \
            2>&1 | tee -a /tmp/output-evolution.txt
    fi
done

# evolved db
echo ""
echo "Creating database description."
python3 -m cdedb_setup dev execute-sql-script -v \
     -f bin/describe_database.sql > /tmp/evolved-description.txt

make i18n-compile
python3 -m cdedb_setup dev compile-sample-data

# new db
echo ""
echo "Resetting and creating database description again."
python3 -m cdedb_setup database create
python3 -m cdedb_setup database populate
python3 -m cdedb_setup dev execute-sql-script -v \
     -f bin/describe_database.sql > /tmp/pristine-description.txt

# perform check
echo ""
echo "DATABASE COMPARISON (this should be empty):"
comm -3 <(sort /tmp/evolved-description.txt) \
     <(sort /tmp/pristine-description.txt) > /tmp/database_difference.txt
cat /tmp/database_difference.txt
echo ""
echo "EVOLUTION OUTPUT:"
cat /tmp/output-evolution.txt
echo ""
echo "OLD: $OLDREVISION NEW: $NEWREVISION"

if [[ -s /tmp/database_difference.txt ]]; then
    exit 1
else
    exit 0
fi
