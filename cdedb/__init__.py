#!/usr/bin/env python3

"""CdE database project.

This application offers an electronic member directory and an academy
coordination component as well as some other functionality to the CdE.
"""

import os
import stat

from cdedb.setup.config import BasicConfig
from cdedb.setup.storage import setup_logger

_BASICCONF = BasicConfig()

# create fallback logger for everything which cannot be covered by another logger
logfile_path = _BASICCONF["LOG_DIR"] / "cdedb.log"
setup_logger("cdedb", logfile_path, _BASICCONF["LOG_LEVEL"],
                 syslog_level=_BASICCONF["SYSLOG_LEVEL"],
                 console_log_level=_BASICCONF["CONSOLE_LOG_LEVEL"])
try:
    # the global log needs to be writable by different users (frontend
    # and backend) making it world writable is pretty permissive but
    # seems to be the most sensible way
    os.chmod(str(logfile_path), stat.S_IRUSR | stat.S_IWUSR |
             stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
except (PermissionError, FileNotFoundError):  # pragma: no cover
    pass
