"""Config for testsuite thread xss."""

import pathlib

from tests.config.base import *  # noqa: F403

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-xss")

STORAGE_DIR = _TMP_DIR / "storage"

CDB_DATABASE_NAME = "cdb_test_xss"
