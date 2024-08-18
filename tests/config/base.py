"""This contains some override config options used in the test suite.

Note that this does is not a complete test config, but only contains the common settings
which are shared by all configurations of the test suite.
"""

import pathlib

# basic config
SYSLOG_LEVEL: int | None = None
CONSOLE_LOG_LEVEL: int | None = None


# config
# TODO make CDEDB_DEV and CDEDB_TEST orthogonal, so the test suite needs only the latter
CDEDB_DEV = True
CDEDB_TEST = True

# docker specific
if pathlib.Path('/CONTAINER').is_file():
    DB_HOST = "cdb"
    DB_PORT = 5432
