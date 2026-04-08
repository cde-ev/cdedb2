#!/bin/bash

COUNT=0

function notice_lines () {
    COUNT=$((COUNT + $1))
}

if [ $# -gt 0 ]
then
    function push_stable () {
        echo "Omitted push."
    }
else
    function push_stable () {
        OLD_TAG="$(git describe --tags origin/stable)"
        TAG=release/$(date +'%Y-%m-%d')
        RELEASE_FILE="related/release/${OLD_TAG#"release/"}_${TAG#"release/"}_$(git rev-parse HEAD | head -c8).md"
        git tag -f "$TAG"
        mkdir related/release
        bin/create_release_description.py "$OLD_TAG" "$TAG" > "$RELEASE_FILE"
        echo "Wrote release note template to '$RELEASE_FILE'."
        git push --delete origin "$TAG"
        git push origin stable tag "$TAG"
        git push --delete mirror "$TAG"
        git push mirror stable tag "$TAG"
    }
fi

for rev in $(git rev-list origin/stable..stable); do
    notice_lines "$(git show -s "$rev" | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /" | wc -l)"
    git show -s "$rev" | grep -i '^\W*Deploy:' | sed -e "s/^\W*/${rev:0:8} /"
done

notice_lines "$(git diff --name-status origin/stable..stable | grep -c "^A\s*related/deploy")"
git diff --name-status origin/stable..stable | grep "^A\s*related/deploy"

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
