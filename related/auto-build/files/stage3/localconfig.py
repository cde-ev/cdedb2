#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import pathlib

# BasicConfig

LOG_DIR = pathlib.Path("/var/log/cdedb")

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

# Config

CDEDB_DEV = True

if pathlib.Path('/CONTAINER').is_file():
    # ldap host server differs for vms and docker containers
    LDAP_HOST = "ldap"
