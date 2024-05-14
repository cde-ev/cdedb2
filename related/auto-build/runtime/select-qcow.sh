#!/bin/bash
NUM=$(ls -1 ./*.qcow2 | wc -l)

if (( NUM == 0 )); then
    >&2 echo "No qcow image found."
    exit 1
elif (( NUM > 1 )); then
    >&2 echo "More than one qcow image. Confused script cannot continue."
    exit 2
fi

echo "$(ls -1 ./*.qcow2)"
