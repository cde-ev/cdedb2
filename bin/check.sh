#!/bin/bash

cd "$(dirname "$0")/.." && TESTPATTERNS="$1" make check

