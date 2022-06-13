#!/bin/bash
set -e


DATABASE_NAME=cdb_test_1

OLDREVISION=$1
NEWREVISION=$2


cd /cdedb2

# create temporary config file to override the default DATABASE_NAME
tmp_configfile=$(mktemp -t config_XXXXXX.py)
cp "$(python3 -m cdedb config default-configpath)" $tmp_configfile
echo 'CDB_DATABASE_NAME="cdb_test_1"' >> $tmp_configfile
chmod +r $tmp_configfile
export CDEDB_CONFIGPATH=$tmp_configfile

# silence git output after switching to a detached head
git config advice.detachedHead false

# old revision
echo ""
echo "Checkout $OLDREVISION"
git checkout $OLDREVISION
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
# Leave this setting in place – the history shows that there will be a time the syntax
# changes and we need this again...
if git merge-base --is-ancestor 3879ebfc9c573100ec6ef82fac324f37fd0e0f09 $OLDREVISION; then
    python3 -m cdedb dev compile-sample-data-sql --outfile - > tests/ancillary_files/sample_data.sql
    python3 -m cdedb db create
    python3 -m cdedb db populate
else
    python3 -m cdedb dev compile-sample-data --outfile - > tests/ancillary_files/sample_data.sql
    python3 -m cdedb db create
    python3 -m cdedb db populate
fi

# new revision
echo ""
echo "Checkout $NEWREVISION"
git checkout $NEWREVISION

# determine evolutions to apply.
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt > /tmp/todoevolutions.txt

# apply all evolutions and gather the output.
truncate -s0 /tmp/output-evolution.txt
while read -r evolution; do
    if [[ $evolution == *.sql ]]; then
        echo ""
        echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
        python3 -m cdedb dev execute-sql-script -v \
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
done < /tmp/todoevolutions.txt

# evolved db
echo ""
echo "Creating database description."
python3 -m cdedb dev execute-sql-script -v \
     -f bin/describe_database.sql > /tmp/evolved-description.txt

make i18n-compile
python3 -m cdedb dev compile-sample-data-sql --outfile - > tests/ancillary_files/sample_data.sql

# new db
echo ""
echo "Resetting and creating database description again."
python3 -m cdedb db create
python3 -m cdedb db populate
python3 -m cdedb dev execute-sql-script -v \
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

rm $tmp_configfile

if [[ -s /tmp/database_difference.txt ]]; then
    exit 1
else
    exit 0
fi
