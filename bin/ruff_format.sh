#!/bin/bash

source .ruff_targets

echo -e "Running ruff isort ...\n"
python3 -m ruff check --select I --fix $ISORT_TARGETS

echo -e "Running ruff format ...\n"
python3 -m ruff format $FORMAT_TARGETS

echo -e "Running ruff check ...\n"
python3 -m ruff check --output-format full $LINT_TARGETS
