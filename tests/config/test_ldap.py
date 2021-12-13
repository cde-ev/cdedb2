"""This contains some override config options used in the test suite.

The structure follows those of the default config in cdedb2.config
"""

import pathlib

################
# Basic config #
################
SYSLOG_LEVEL = None
CONSOLE_LOG_LEVEL = None


################
# Global stuff #
################

# CDB_DATABASE_NAME = os.environ['CDEDB_TEST_DATABASE']
# STORAGE_DIR = pathlib.Path(os.environ['CDEDB_TEST_TMP_DIR'], 'storage')
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-ldap")

CDB_DATABASE_NAME = "cdb_test_ldap"

CDEDB_TEST = True

STORAGE_DIR = _TMP_DIR / "storage"

if pathlib.Path('/CONTAINER').is_file():
    # ldap host server differs for vms and docker containers
    LDAP_HOST = "ldap"


#############
# Log stuff #
#############

# _LOG_ROOT = pathlib.Path(os.environ['CDEDB_TEST_TMP_DIR'], 'logs')
_LOG_ROOT = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR

GLOBAL_LOG = _LOG_ROOT / "global.log"

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

TIMING_LOG = _LOG_ROOT / "timing.log"
