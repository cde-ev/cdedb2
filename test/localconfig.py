#!/usr/bin/env python3

import pathlib

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
