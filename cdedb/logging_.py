"""Everything to setup our logging facility."""

import logging
import os
import pathlib
import sys

from systemd.journal import JournalHandler

from cdedb.config import DEFAULT_LOG_LEVEL, Config


def setup_root_logger() -> None:
    # loggers are hierachical - configuring handlers and setting a loglevel for logger
    # "cdedb" is sufficient to configure all child loggers, like "cdedb.backend".
    logger = logging.getLogger()

    # we can not rely on the config at this point, since this code will be executed
    # while importing the cdedb module. Therefore, we apply the default log level
    # specified in the config, and reapply the custom log level of the config
    # at first config access.
    loglevel = DEFAULT_LOG_LEVEL
    logger.setLevel(loglevel)

    # ignore errors inside the logging system on prod
    if pathlib.Path("/PRODUCTIONVM").is_file():
        logging.raiseExceptions = False

    # setup handler
    handler: logging.Handler = MyJournalHandler(SYSLOG_IDENTIFIER="cdedb")
    if (is_container := pathlib.Path("/CONTAINER").is_file()):
        # do not log anything in the CI
        if os.environ.get("CI"):
            handler = logging.NullHandler()
        else:
            handler = logging.StreamHandler(sys.stdout)
    formatstr = (
        ("[{asctime}]" if is_container else "") +
        " [{name}]"
        " [{levelname}]"
        " [{funcName} in {pathname} line {lineno}]"
        " [{CDB_DATABASE_NAME}]"
        " {message}"
    ).strip()
    handler.setFormatter(MyFormatter(formatstr, style="{"))
    handler.setLevel(loglevel)
    logger.addHandler(handler)

    logger.info("Logger successfully set up.")


class MyFormatter(logging.Formatter):
    _config = Config()
    default_time_format = '%Y-%m-%d %H:%M:%S %z'
    default_msec_format = None

    def format(self, record: logging.LogRecord) -> str:
        # to distinguish between tests
        setattr(record, "CDB_DATABASE_NAME", self._config["CDB_DATABASE_NAME"])
        return super().format(record)


class MyJournalHandler(JournalHandler):
    _config = Config()

    def emit(self, record: logging.LogRecord) -> None:
        # to distinguish between tests
        setattr(record, "CDB_DATABASE_NAME", self._config["CDB_DATABASE_NAME"])
        return super().emit(record)
