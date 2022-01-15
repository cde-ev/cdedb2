"""This contains some override config options used in the test suite.

The structure follows those of the default config in cdedb2.config
"""

import pathlib

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-2")


# basic config
SYSLOG_LEVEL = None
CONSOLE_LOG_LEVEL = None
LOG_DIR = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR


# config
CDB_DATABASE_NAME = "cdb_test_2"
CDEDB_TEST = True
STORAGE_DIR = _TMP_DIR / "storage"

# docker specific
if pathlib.Path('/CONTAINER').is_file():
    DB_HOST = "cdb"
    DB_PORT = 5432
