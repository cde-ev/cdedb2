#!/bin/bash

COUNT=0

function notice_lines () {
    COUNT=$(($COUNT + $1))
}

for rev in $(git rev-list origin/stable..stable); do
    notice_lines $(git show $rev | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /" | wc -l)
    git show $rev | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /"
done

if [ $COUNT -gt 0 ]
then
    echo ""
    select yn in "Push" "Abort"; do
        case $yn in
            Push ) git push origin stable
                  break;;
            Abort ) exit;;
        esac
    done

else
    git push origin stable
fi
