#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import os
import pathlib

# check for test environment
CDEDB_TEST = os.environ.get('CDEDB_TEST')

# BasicConfig

LOG_DIR = (pathlib.Path(os.environ['CDEDB_TEST_TMP_DIR'], 'logs') if CDEDB_TEST
           else pathlib.Path("/var/log/cdedb"))

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO
# TODO why is this named different fromt the default?
GLOBAL_LOG_FILE = "global.log"

if CDEDB_TEST:
    SYSLOG_LEVEL = None  # type: ignore
    CONSOLE_LOG_LEVEL = None  # type: ignore

# Config

CDEDB_DEV = True

if pathlib.Path('/CONTAINER').is_file():
    # ldap host server differs for vms and docker containers
    LDAP_HOST = "ldap"

if CDEDB_TEST:
    CDB_DATABASE_NAME = os.environ['CDEDB_TEST_DATABASE']
    SERVER_NAME_TEMPLATE = "test_{}_server"
    STORAGE_DIR = pathlib.Path(os.environ['CDEDB_TEST_TMP_DIR'], 'storage')
