#!/bin/bash

cd "$(dirname "$0")/.." && TESTPATTERN="$1" make check

