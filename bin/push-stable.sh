#!/bin/bash

COUNT=0

function notice_lines () {
    COUNT=$(($COUNT + $1))
}

if [ $# -gt 0 ]
then
    function push_stable () {
        echo "Omitted push."
    }
else
    function push_stable () {
        git tag release/$(date +'%Y-%m-%d')
        git push origin stable --tags
        git push mirror stable
    }
fi

for rev in $(git rev-list origin/stable..stable); do
    notice_lines $(git show -s $rev | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /" | wc -l)
    git show -s $rev | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /"
done

if [ $COUNT -gt 0 ]
then
    echo ""
    select yn in "Push" "Abort"; do
        case $yn in
            Push ) push_stable
                   break;;
            Abort ) exit;;
        esac
    done

else
    push_stable
fi
