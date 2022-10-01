#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import pathlib

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

CDEDB_DEV = True

if pathlib.Path('/CONTAINER').is_file():
    # postgres and ldap are reachable under their own hostname instead of localhost
    DB_HOST = "cdb"
    LDAP_HOST = "ldap"
    LDAP_PEM_PATH = pathlib.Path("/etc/ldap/certs/ldap.pem")
    LDAP_KEY_PATH = pathlib.Path("/etc/ldap/certs/ldap.key")
    # there is no pgbouncer so the postgres port is the original one
    DB_PORT = 5432
