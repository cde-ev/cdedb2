#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import os
import pathlib

# check for test environment

CDEDB_TEST = os.environ.get('CDEDB_TEST')

# BasicConfig

_LOG_ROOT = pathlib.Path("/var/log/cdedb")

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO
GLOBAL_LOG = _LOG_ROOT / "global.log"

if CDEDB_TEST:
    SYSLOG_LEVEL = None  # type: ignore
    CONSOLE_LOG_LEVEL = None  # type: ignore
    GLOBAL_LOG = pathlib.Path("/tmp/test-cdedb.log")

# Config

CDEDB_DEV = True

FRONTEND_LOG = _LOG_ROOT / "frontend.log"
CORE_FRONTEND_LOG = _LOG_ROOT / "frontend-core.log"
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
CRON_FRONTEND_LOG = _LOG_ROOT / "frontend-cron.log"
WORKER_LOG = _LOG_ROOT / "frontend-worker.log"
MAILMAN_LOG = _LOG_ROOT / "frontend-mailman.log"

if CDEDB_TEST:
    DB_PORT = 6432
    CDB_DATABASE_NAME = os.environ['TESTDBNAME']
    # TODO: use this constant everywhere instead of hardcoded os.environ element
    SERVER_NAME_TEMPLATE = "test_{}_server"
    STORAGE_DIR = pathlib.Path("/tmp/cdedb-store/")
    FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend.log")
    CRON_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-cron.log")
    BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend.log")
    CORE_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-core.log")
    CORE_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-core.log")
    SESSION_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-session.log")
    CDE_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-cde.log")
    CDE_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-cde.log")
    EVENT_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-event.log")
    EVENT_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-event.log")
    PAST_EVENT_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-past-event.log")
    ML_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-ml.log")
    ML_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-ml.log")
    ASSEMBLY_FRONTEND_LOG = pathlib.Path("/tmp/test-cdedb-frontend-assembly.log")
    ASSEMBLY_BACKEND_LOG = pathlib.Path("/tmp/test-cdedb-backend-assembly.log")
    WORKER_LOG = pathlib.Path("/tmp/test-cdedb-frontend-worker.log")
    MAILMAN_LOG = pathlib.Path("/tmp/test-cdedb-frontend-mailman.log")
