"""Config for testsuite thread xss."""

import pathlib

from tests.config.base import *  # type: ignore[import]

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-1")

LOG_DIR = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR
STORAGE_DIR = _TMP_DIR / "storage"

CDB_DATABASE_NAME = "cdb_test_xss"


# test config
XSS_OUTDIR = pathlib.Path("./out")
XSS_PAYLOAD = "<script>abcdef</script>"
XSS_PAYLOAD_SECONDARY = [
    "&amp;lt;",
    "&amp;gt;",
]
