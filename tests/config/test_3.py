"""Config for testsuite thread 3."""

import pathlib

from tests.config.base import *  # noqa: F403

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-3")

LOG_DIR = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR
STORAGE_DIR = _TMP_DIR / "storage"

CDB_DATABASE_NAME = "cdb_test_3"
