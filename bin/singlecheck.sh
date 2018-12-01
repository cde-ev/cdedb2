#!/bin/bash

cd "$(dirname "$0")/.." && TESTNAME="$1" TESTFILE="$2" make new-single-check
