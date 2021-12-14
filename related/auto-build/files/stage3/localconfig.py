#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import pathlib

# BasicConfig

_LOG_ROOT = pathlib.Path("/var/log/cdedb")

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO
GLOBAL_LOG = _LOG_ROOT / "global.log"

# Config

CDEDB_DEV = True

FRONTEND_LOG = _LOG_ROOT / "frontend.log"
CORE_FRONTEND_LOG = _LOG_ROOT / "frontend-core.log"
CRON_FRONTEND_LOG = _LOG_ROOT / "frontend-cron.log"
CDE_FRONTEND_LOG = _LOG_ROOT / "frontend-cde.log"
EVENT_FRONTEND_LOG = _LOG_ROOT / "frontend-event.log"
ML_FRONTEND_LOG = _LOG_ROOT / "frontend-ml.log"
ASSEMBLY_FRONTEND_LOG = _LOG_ROOT / "frontend-assembly.log"
BACKEND_LOG = _LOG_ROOT / "backend.log"
CORE_BACKEND_LOG = _LOG_ROOT / "backend-core.log"
SESSION_BACKEND_LOG = _LOG_ROOT / "backend-session.log"
CDE_BACKEND_LOG = _LOG_ROOT / "backend-cde.log"
EVENT_BACKEND_LOG = _LOG_ROOT / "backend-event.log"
PAST_EVENT_BACKEND_LOG = _LOG_ROOT / "backend-past-event.log"
ML_BACKEND_LOG = _LOG_ROOT / "backend-ml.log"
ASSEMBLY_BACKEND_LOG = _LOG_ROOT / "backend-assembly.log"
WORKER_LOG = _LOG_ROOT / "frontend-worker.log"
MAILMAN_LOG = _LOG_ROOT / "frontend-mailman.log"

if pathlib.Path('/CONTAINER').is_file():
    # ldap host server differs for vms and docker containers
    LDAP_HOST = "ldap"
