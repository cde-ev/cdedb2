#!/bin/bash


EXENAME=$(basename $0)

# This command has two operation modes:
#   (i) as a pseudo CI isolated command inside a one time use container
#   (ii) as an interactive diagnostic
#
# The main differences are that (i) is much more thorough and that (ii) is
# more careful to not destroy data on the instance it's run on.

if [[ "$EXENAME" == inside-isolated-evolution.sh ]]; then
    ISOLATED=true
elif [[ "$EXENAME" == evolution-trial.sh ]]; then
    ISOLATED=false
else
    echo "Unknown command"
    exit
fi

if [[ "$ISOLATED" == true ]]; then
    OLDREVISION=$2
    NEWREVISION=$3
else
    if [[ $# -ne 2 ]]; then
        echo "Usage: $(basename $0) old-revision new-revision"
        exit
    fi
    OLDREVISION=$1
    NEWREVISION=$2
fi


export TESTPREPARATION=manual
cd /cdedb2
if [[ "$ISOLATED" == true ]]; then
    git pull &> /dev/null
fi

# old revision
echo "Checkout $OLDREVISION"
git checkout $OLDREVISION &> /dev/null
git pull &> /dev/null
ls cdedb/database/evolutions > /tmp/oldevolutions.txt
make -B test/ancillary_files/sample_data.sql &> /dev/null
if [[ "$ISOLATED" == true ]]; then
    make sample-data &> /dev/null
    make sample-data-test &> /dev/null
else
    make sql-test &> /dev/null
fi

# new revision
echo "Checkout $NEWREVISION"
git checkout $NEWREVISION &> /dev/null
git pull &> /dev/null
ls cdedb/database/evolutions | sort > /tmp/newevolutions.txt
grep /tmp/newevolutions.txt -v -f /tmp/oldevolutions.txt \
     > /tmp/todoevolutions.txt
truncate -s0 /tmp/output-evolution.txt
for evolution in $(cat /tmp/todoevolutions.txt); do
    echo "Apply evolution $evolution" | tee -a /tmp/output-evolution.txt
    sudo -u cdb psql -U cdb -d cdb_test \
         -f cdedb/database/evolutions/$evolution \
         2>&1 | tee -a /tmp/output-evolution.txt
done

# evolved db
echo "Creating database description."
sudo -u postgres psql -U postgres -d cdb_test \
     -f bin/describe_database.sql > /tmp/evolved-description.txt
bin/normalize_database_description.py /tmp/evolved-description.txt

make i18n-compile
make -B test/ancillary_files/sample_data.sql &> /dev/null
if [[ "$ISOLATED" == true ]]; then
    make sample-data-test-shallow
    ./bin/check.sh 2> >(tee -a /tmp/output-check.txt >&2)
fi

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
if [[ "$ISOLATED" == true ]]; then
    echo "CONDENSED REPORT:"
    grep -E '^(ERROR|FAIL):' /tmp/output-check.txt
    echo ""
fi
echo "EVOLUTION OUTPUT:"
cat /tmp/output-evolution.txt
echo ""
echo "OLD: $OLDREVISION NEW: $NEWREVISION"

if [[ "$ISOLATED" == true ]]; then
    sudo shutdown -h now
fi
