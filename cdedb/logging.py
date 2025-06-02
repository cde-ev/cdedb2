"""Everything to setup our logging facility."""

import logging
import pathlib
import sys

from systemd.journal import JournalHandler

from cdedb.config import Config


def setup_cdedb_root_logger() -> None:
    # loggers are hierachical - configuring handlers and setting a loglevel for logger
    # "cdedb" is sufficient to configure all child loggers, like "cdedb.backend".
    logger = logging.getLogger("cdedb")
    # do not propagate log messages to the root logger
    logger.propagate = False

    # we can not rely on the config at this point, since this code will be executed
    # while importing the cdedb module. Therefore, we only distinguish between
    # production, CI/docker and vm.
    loglevel = logging.INFO
    if is_production := pathlib.Path("/PRODUCTIONVM").is_file():
        loglevel = logging.WARNING
    elif pathlib.Path('/CONTAINER').is_file():
        loglevel = logging.WARNING
    logger.setLevel(loglevel)

    # ignore errors inside the logging system on prod
    if is_production:
        logging.raiseExceptions = False

    # setup handler
    handler: logging.Handler = MyJournalHandler(SYSLOG_IDENTIFIER="cdedb")
    if pathlib.Path("/CONTAINER").is_file():
        handler = logging.StreamHandler(sys.stdout)
        # imitate the information saved to the journal
        formatstr = (
            "[{asctime}]"
            " [{name}]"
            " [{levelname}]"
            " [{funcName} in {pathname} line {lineno}]"
            " [{CDB_DATABASE_NAME}]"
            " {message}"
        )
        handler.setFormatter(MyFormatter(formatstr, style="{"))
    handler.setLevel(loglevel)
    logger.addHandler(handler)

    logger.info("Logger successfully set up.")


class MyFormatter(logging.Formatter):
    _config = Config()

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
