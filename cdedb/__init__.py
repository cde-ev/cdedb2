#!/usr/bin/env python3

"""CdE database project.

This application offers an electronic member directory and an academy
coordination component as well as some other functionality to the CdE.
"""

import os
import stat

from cdedb_setup.config import Config
from cdedb_setup.storage import setup_logger

conf = Config()

# create fallback logger for everything which cannot be covered by another logger
logger_path = conf["LOG_DIR"] / "cdedb.log"
setup_logger("cdedb", logger_path, conf["LOG_LEVEL"],
             syslog_level=conf["SYSLOG_LEVEL"],
             console_log_level=conf["CONSOLE_LOG_LEVEL"])
try:
    # the global log needs to be writable by different users (frontend
    # and backend) making it world writable is pretty permissive but
    # seems to be the most sensible way
    os.chmod(str(logger_path), stat.S_IRUSR | stat.S_IWUSR |
             stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
except (PermissionError, FileNotFoundError):  # pragma: no cover
    pass
