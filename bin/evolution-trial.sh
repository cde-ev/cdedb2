#!/bin/bash
set -e

OLDREVISION=$1
NEWREVISION=$2


cd /cdedb2

# silence git output after switching to a detached head
git config advice.detachedHead false

if [[ "$(git rev-parse $OLDREVISION^{})" = "$(git rev-parse $NEWREVISION^{})" ]]; then
    echo "Source and target are identical."
    exit 0
fi

# old revision
echo ""
echo "Checkout $OLDREVISION"
git checkout $OLDREVISION

echo ""
echo "Creating pristine database and gathering list of evolutions."
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
# Leave this setting in place – the history shows that there will be a time the syntax
# changes and we need this again...
if git merge-base --is-ancestor 5f18f7e5239fc4c10b6c79dfdd4b68a260a99e00 $OLDREVISION; then
    python3 -m cdedb dev apply-evolution-trial
else
    python3 -m cdedb db create-users
    python3 -m cdedb db create
    python3 -m cdedb db populate
fi

# new revision
echo ""
echo "Checkout $NEWREVISION"
git checkout $NEWREVISION

# determine evolutions to apply.
echo ""
echo "Compiling list of evolutions to apply:"
truncate -s0 /tmp/todoevolutions.txt
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
(grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt > /tmp/todoevolutions.txt) || true
echo ""
cat /tmp/todoevolutions.txt

# apply all evolutions and gather the output.
evolution_output=/tmp/output-evolution.txt
touch $evolution_output
sudo chown root $evolution_output
sudo chmod a+rw $evolution_output
truncate -s0 $evolution_output
while read -r evolution; do
    if [[ $evolution == *.postgres.sql ]]; then
        echo ""
        echo "Apply evolution $evolution as postgres database user."| tee -a /tmp/output-evolution.txt
        sudo CDEDB_CONFIGPATH=$CDEDB_CONFIGPATH POSTGRES_PASSWORD=$POSTGRES_PASSWORD \
             python3 -m cdedb dev execute-sql-script --as-postgres -vv \
             -f cdedb/database/evolutions/$evolution \
             -o $evolution_output --outfile-append
    elif [[ $evolution == *.sql ]]; then
        echo ""
        echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
        python3 -m cdedb dev execute-sql-script -vv \
             -f cdedb/database/evolutions/$evolution \
             -o $evolution_output --outfile-append
    elif [[ $evolution == *.py ]]; then
        echo ""
        echo "Run migration script $evolution" | tee -a /tmp/output-evolution.txt
        # we use a testconfig for the ci call, so we need to make the test module accessible
        PYTHONPATH="$(python3 -m cdedb config get REPOSITORY_PATH)"
        sudo -u www-data \
            EVOLUTION_TRIAL_OVERRIDE_DRY_RUN='' \
            EVOLUTION_TRIAL_OVERRIDE_PERSONA_ID=1 \
            EVOLUTION_TRIAL_OVERRIDE_OUTFILE=$evolution_output \
            EVOLUTION_TRIAL_OVERRIDE_OUTFILE_APPEND=1 \
            PYTHONPATH=$PYTHONPATH \
            CDEDB_CONFIGPATH=$CDEDB_CONFIGPATH \
            python3 cdedb/database/evolutions/$evolution
    else
        echo "Unhandled evolution $evolution" | tee -a /tmp/output-evolution.txt
    fi
done < /tmp/todoevolutions.txt

# evolved db
echo ""
echo "Creating database description."
python3 -m cdedb dev describe-database -o /tmp/evolved-description.txt

# new db
echo ""
echo "Resetting and creating database description again."
make i18n-compile
python3 -m cdedb dev apply-evolution-trial
python3 -m cdedb dev describe-database -o /tmp/pristine-description.txt

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
