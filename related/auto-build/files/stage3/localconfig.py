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

if CDEDB_TEST:
    SYSLOG_LEVEL = None  # type: ignore
    CONSOLE_LOG_LEVEL = None  # type: ignore

# Config

CDEDB_DEV = True

if pathlib.Path('/CONTAINER').is_file():
    # postgres and ldap are reachable under their own hostname instead of localhost
    DB_HOST = "cdb"
    LDAP_HOST = "ldap"
    # there is no pgbouncer so the postgres port is the original one
    DB_PORT = 5432

if CDEDB_TEST:
    CDB_DATABASE_NAME = os.environ['CDEDB_TEST_DATABASE']
    SERVER_NAME_TEMPLATE = "test_{}_server"
    STORAGE_DIR = pathlib.Path(os.environ['CDEDB_TEST_TMP_DIR'], 'storage')
