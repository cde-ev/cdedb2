#!/bin/bash

if [[ $# -lt 1 ]]; then
    cd "$(dirname "$0")/.." && make check
else
    cd "$(dirname "$0")/.." && TESTPATTERN="$1" make check
fi

