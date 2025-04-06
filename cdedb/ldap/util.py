"""Custom types for LDAP"""

import logging
import logging.handlers
import sys
from collections.abc import Sequence
from typing import Any, NewType, TypeAlias

from ldaptor.protocols import pureldap

from cdedb.config import Config

AttributeDescriptionList = NewType("AttributeDescriptionList", Sequence[Any])
FilterLike: TypeAlias = pureldap.LDAPFilter | pureldap.LDAPFilterSet


def setup_logger(name: str, config: Config) -> logging.Logger:
    """Mimics setup_logger in cdedb.common."""
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.debug(f"Logger {name} already initialized.")
        return logger

    logger.propagate = False
    logger.setLevel(config["LOG_LEVEL"])
    formatter = logging.Formatter('[%(asctime)s,%(name)s,%(levelname)s] %(message)s')

    logfile_path = config["LOG_DIR"] / f"{name.replace('.', '-')}.log"
    file_handler = logging.FileHandler(str(logfile_path), delay=True, encoding='utf-8')
    file_handler.setLevel(config["LOG_LEVEL"])
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if config["SYSLOG_LEVEL"]:
        syslog_handler = logging.handlers.SysLogHandler()
        syslog_handler.setLevel(config["SYSLOG_LEVEL"])
        syslog_handler.setFormatter(formatter)
        logger.addHandler(syslog_handler)
    if config["CONSOLE_LOG_LEVEL"]:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(config["CONSOLE_LOG_LEVEL"])
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
