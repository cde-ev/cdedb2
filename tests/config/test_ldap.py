"""Config for testsuite thread ldap."""

import pathlib

from tests.config.base import *  # type: ignore[import]

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-ldap")

LOG_DIR = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR
STORAGE_DIR = _TMP_DIR / "storage"

CDB_DATABASE_NAME = "cdb_test_ldap"

# change the ldap host in docker
if pathlib.Path('/CONTAINER').is_file():
    LDAP_HOST = "ldap"
