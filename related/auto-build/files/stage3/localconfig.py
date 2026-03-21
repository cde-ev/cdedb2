#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import pathlib

CDEDB_DEV = True

if pathlib.Path('/CONTAINER').is_file():
    # postgres and ldap are reachable under their own hostname instead of localhost
    DB_HOST = "cdb"
    LDAP_HOST = "ldap"
    LDAP_PEM_PATH = pathlib.Path("/etc/ssl/ldap/ldap.pem")
    LDAP_KEY_PATH = pathlib.Path("/etc/ssl/ldap/ldap.key")
    # there is no pgbouncer so the postgres port is the original one
    DB_PORT = 5432

    # in docker, we need to print every log message to stdout, which makes it
    # quite cumbersome to run command from the terminal.
    LOG_LEVEL = logging.DEBUG

# dPROD relevant excerpt from actual config follows:
# SECRETS_CONFIGPATH = pathlib.Path("/etc/cdedb/secrets.py")
# MAILMAN_HOST = "10.10.0.2:8001"
# LDAP_HOST = "ldap.cde-ev.de"
# LDAP_PEM_PATH = pathlib.Path("/var/local/letsencrypt/certs/ldap.cde-ev.de.pem")
# LDAP_KEY_PATH = pathlib.Path("/etc/letsencrypt/domainkeys/ldap.cde-ev.de.key")
