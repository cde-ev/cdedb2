#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging
import os
import pathlib

# check for test environment

CDEDB_TEST = os.environ.get('CDEDB_TEST', '').lower() in ('true', 't')

# BasicConfig

LOG_LEVEL = logging.DEBUG
SYSLOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.WARNING
GLOBAL_LOG = pathlib.Path("/log/cdedb.log")

if CDEDB_TEST:
    SYSLOG_LEVEL = None
    CONSOLE_LOG_LEVEL = None
    GLOBAL_LOG = pathlib.Path("/tmp/test-cdedb.log")

# Config

CDEDB_DEV = True
FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend.log")
CORE_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-core.log")
CDE_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-cde.log")
EVENT_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-event.log")
ML_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-ml.log")
ASSEMBLY_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-assembly.log")
BACKEND_LOG = pathlib.Path("/log/cdedb-backend.log")
CORE_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-core.log")
SESSION_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-session.log")
CDE_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-cde.log")
EVENT_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-event.log")
PAST_EVENT_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-past-event.log")
ML_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-ml.log")
ASSEMBLY_BACKEND_LOG = pathlib.Path("/log/cdedb-backend-assembly.log")
CRON_FRONTEND_LOG = pathlib.Path("/log/cdedb-frontend-cron.log")
WORKER_LOG = pathlib.Path("/log/cdedb-frontend-worker.log")

if CDEDB_TEST:
    DB_PORT = 6432
    CDB_DATABASE_NAME = "cdb_test"
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
