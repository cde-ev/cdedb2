#!/usr/bin/env python3

"""CdE database project.

This application offers an electronic member directory and an academy
coordination component as well as some other functionality to the CdE.
"""

import os
import stat

from cdedb.common import make_root_logger
from cdedb.config import BasicConfig

_BASICCONF = BasicConfig()

# create fallback logger for everything which cannot be covered by
# another logger
make_root_logger("cdedb", _BASICCONF["GLOBAL_LOG"], _BASICCONF["LOG_LEVEL"],
                 syslog_level=_BASICCONF["SYSLOG_LEVEL"],
                 console_log_level=_BASICCONF["CONSOLE_LOG_LEVEL"])
try:
    # the global log needs to be writable by different users (frontend
    # and backend) making it world writable is pretty permissive but
    # seems to be the most sensible way
    os.chmod(str(_BASICCONF["GLOBAL_LOG"]), stat.S_IRUSR | stat.S_IWUSR |
             stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
except (PermissionError, FileNotFoundError):  # pragma: no cover
    pass
