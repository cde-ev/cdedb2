"""Everything to setup our logging facility."""

import logging
import os
import pathlib
import sys

from cysystemd.journal import JournaldLogHandler

from cdedb.config import DEFAULT_LOG_LEVEL, Config


def setup_root_logger(*, test: bool = False, replace: bool = False) -> None:
    # loggers are hierachical - configuring handlers and setting a loglevel for logger
    # "cdedb" is sufficient to configure all child loggers, like "cdedb.backend".
    logger = logging.getLogger()

    if replace:
        for h in logger.handlers:
            logger.removeHandler(h)

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
    identifier = "cdedb" if not test else "cdedb-test"
    handler: logging.Handler = JournaldLogHandler(identifier=identifier)
    if is_container := pathlib.Path("/CONTAINER").is_file():
        # do not log anything in the CI
        if os.environ.get("CI"):
            handler = logging.NullHandler()
        else:
            handler = logging.StreamHandler(sys.stdout)
    formatstr = (
        ("[{asctime}]" if is_container else "") +
        " [{name}]"
        " [{levelname}]"
        " [{funcName} in {pathname}:{lineno}]"
        " {message}"
    ).strip()  # fmt: skip
    handler.setFormatter(MyFormatter(formatstr, style="{"))
    handler.setLevel(loglevel)
    logger.addHandler(handler)

    logger.info(f"Logger {identifier} successfully set up.")


class MyFormatter(logging.Formatter):
    _config = Config()
    default_time_format = '%Y-%m-%d %H:%M:%S %z'
    default_msec_format = None

    def format(self, record: logging.LogRecord) -> str:
        # Getting a key from the config may cause a log entry.
        #  Therefore we access the '_configchain' directly to avoid recursion.

        # to distinguish between tests
        if self._config._configchain["CDEDB_TEST"]:
            record.name += (
                "-" + self._config._configchain["CDB_DATABASE_NAME"].split("_")[-1]
            )
        setattr(
            record, "CDB_DATABASE_NAME", self._config._configchain["CDB_DATABASE_NAME"]
        )
        return super().format(record)
