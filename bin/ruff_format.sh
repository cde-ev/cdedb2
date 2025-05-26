#!/bin/bash

source .ruff_targets

echo -e "Running ruff format ...\n"
ruff format $FORMAT_TARGETS

echo -e "Running ruff isort ...\n"
ruff check --select I --fix $ISORT_TARGETS

echo -e "Running ruff check ...\n"
ruff check --output-format full $LINT_TARGETS
