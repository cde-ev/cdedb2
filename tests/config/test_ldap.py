"""Config for testsuite thread ldap."""

import pathlib

from tests.config.base import *  # type: ignore[import]

# temporary directory created during the test run for this test thread
_TMP_DIR = pathlib.Path("/tmp/cdedb-test-ldap")

LOG_DIR = _TMP_DIR / "logs"  # May not be inside STORAGE_DIR
STORAGE_DIR = _TMP_DIR / "storage"

CDB_DATABASE_NAME = "cdb_test_ldap"

# switch the port, so we do not collide with the real ldap server at port 636
LDAP_PORT = 20636

# change the ldap host in docker
if pathlib.Path('/CONTAINER').is_file():
    LDAP_HOST = "ldap"
    # there is only a single ldap server running for docker, which needs to be used
    # for tests and development
    LDAP_PORT = 636
    LDAP_PEM_PATH = pathlib.Path("/etc/ssl/ldap/ldap.pem")
    LDAP_KEY_PATH = pathlib.Path("/etc/ssl/ldap/ldap.key")
