#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging

CDEDB_DEV = True
LOG_LEVEL = logging.DEBUG
SYSLOG_LOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

GLOBAL_LOG = "/log/cdedb.log"
FRONTEND_LOG = "/log/cdedb-frontend.log"
CORE_FRONTEND_LOG = "/log/cdedb-frontend-core.log"
CDE_FRONTEND_LOG = "/log/cdedb-frontend-cde.log"
EVENT_FRONTEND_LOG = "/log/cdedb-frontend-event.log"
ML_FRONTEND_LOG = "/log/cdedb-frontend-ml.log"
ASSEMBLY_FRONTEND_LOG = "/log/cdedb-frontend-assembly.log"
BACKEND_LOG = "/log/cdedb-backend.log"
CORE_BACKEND_LOG = "/log/cdedb-backend-core.log"
SESSION_BACKEND_LOG = "/log/cdedb-backend-session.log"
CDE_BACKEND_LOG = "/log/cdedb-backend-cde.log"
EVENT_BACKEND_LOG = "/log/cdedb-backend-event.log"
PAST_EVENT_BACKEND_LOG = "/log/cdedb-backend-past-event.log"
ML_BACKEND_LOG = "/log/cdedb-backend-ml.log"
ASSEMBLY_BACKEND_LOG = "/log/cdedb-backend-assembly.log"

try:
    import cdedb.testconfig
    CONSOLE_LOG_LEVEL = cdedb.testconfig.CONSOLE_LOG_LEVEL
    GLOBAL_LOG = cdedb.testconfig.GLOBAL_LOG
except ImportError:
    pass
