#!/usr/bin/env python3

"""Sample configuration for development instances."""

import logging

CDEDB_DEV = True
LOG_LEVEL = logging.DEBUG
SYSLOG_LOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

GLOBAL_LOG = "/log/cdedb.log"
FRONTEND_LOG = "/log/cdedb-frontend.log"
CORE_ACCESS_LOG = "/log/cdedb-access-core.log"
CORE_BACKEND_LOG = "/log/cdedb-backend-core.log"
SESSION_ACCESS_LOG = "/log/cdedb-access-session.log"
SESSION_BACKEND_LOG = "/log/cdedb-backend-session.log"
CDE_ACCESS_LOG = "/log/cdedb-access-cde.log"
CDE_BACKEND_LOG = "/log/cdedb-backend-cde.log"
EVENT_ACCESS_LOG = "/log/cdedb-access-event.log"
EVENT_BACKEND_LOG = "/log/cdedb-backend-event.log"

try:
    import cdedb.testconfig
    CONSOLE_LOG_LEVEL = cdedb.testconfig.CONSOLE_LOG_LEVEL
    GLOBAL_LOG = cdedb.testconfig.GLOBAL_LOG
except ImportError:
    pass
