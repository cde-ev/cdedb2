#!/bin/bash

STABLE=$(git rev-parse stable)
CURRENT=$(git rev-parse HEAD)
git branch -f oldstable "$STABLE"
git branch -f newstable "$CURRENT"
git diff oldstable..newstable cdedb/database/ related/auto-build/ cdedb/config.py
