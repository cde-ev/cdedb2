#!/usr/bin/env python3

import pathlib

# This file provides overrides for config and secrets config
SECRETS_CONFIGPATH = pathlib.Path("tests/ancillary_files/extra_config.py")

# config
DB_PORT = 42
CDB_DATABASE_NAME = "skynet"

# secrets config
URL_PARAMETER_SALT = "matrix"
