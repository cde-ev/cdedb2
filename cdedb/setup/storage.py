"""Set up the file system related stuff, like upload-storage, loggers and log dirs."""
import logging
import logging.handlers
import os
import pathlib
import shutil
import stat
import sys

from cdedb.setup.config import Config
from cdedb.setup.util import sanity_check


def recreate_directory(directory: pathlib.Path) -> None:
    """Create the given directory, or remove its content if it already exists.

    Since the right to create or delete a directory is determined by its parent and not
    by the directory itself, this is a bit tricky. Therefore, this does also some error
    detection about missing permissions.
    """
    if directory.exists():
        # remove the content of the directory
        for path in directory.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
            else:
                raise NotImplementedError
    else:
        try:
            directory.mkdir(parents=True)
        except PermissionError as e:
            msg = (f"Please create the directory {e.filename} manually. Make sure the"
                   f" current user has proper permissions on this directory.")
            raise PermissionError(msg) from e


@sanity_check
def create_storage(conf: Config) -> None:
    """Create the directory structure of the storage directory."""
    storage_dir: pathlib.Path = conf["STORAGE_DIR"]

    subdirs = (
        "foto",  # core: profile fotos
        "genesis_attachment",  # core: genesis attachments
        "minor_form",  # event: minor forms
        "mailman_templates",  # ml: mailman message templates
        "ballot_result",  # assembly: ballot result files
        "assembly_attachment",  # assembly: attachment files
        "testfiles",  # tests: all testfiles
    )

    recreate_directory(storage_dir)
    for subdir in subdirs:
        (storage_dir / subdir).mkdir()


@sanity_check
def populate_storage(conf: Config) -> None:
    """Populate the storage directory with sample data."""
    storage_dir: pathlib.Path = conf["STORAGE_DIR"]
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    if not storage_dir.is_dir():
        raise RuntimeError("Create storage before you populate it.")

    foto = ("e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425"
            "a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9")
    files = (
        "picture.pdf",  # core: profile foto?
        "picture.png",  # core: profile foto
        "picture.jpg",  # core: profile foto
        "batch_admission.csv",  # cde: sample input for batch admission
        "sepapain.xml",  # cde: example result of sepapain lastschrift file
        "statement.csv",  # cde: sample input for parse_statement
        "money_transfers.csv",  # cde: sample input for member fees (money transfers)
        "money_transfers_valid.csv",  # cde: valid sample input for money transfers
        "form.pdf",  # event: sample minor form
        "event_export.json",  # event: example result of full event export
        "TestAka_partial_export_event.json",  # event: example result of partial export
        "partial_event_import.json",  # event: sample input for partial import
        "questionnaire_import.json",  # event: sample input for questionnaire import
        "ballot_result.json",  # assembly: example result for a ballot
        "rechen.pdf",  # assembly: sample attachment
        "kassen.pdf",  # assembly: sample attachment
    )

    testfile_dir: pathlib.Path = repo_path / "tests" / "ancillary_files"
    attachment_dir = storage_dir / "assembly_attachment"

    shutil.copy(testfile_dir / foto, storage_dir / "foto")
    shutil.copy(testfile_dir / "rechen.pdf", attachment_dir / "1_v1")
    shutil.copy(testfile_dir / "kassen.pdf", attachment_dir / "2_v1")
    shutil.copy(testfile_dir / "kassen2.pdf", attachment_dir / "2_v3")
    shutil.copy(testfile_dir / "kandidaten.pdf", attachment_dir / "3_v1")
    for file in files:
        shutil.copy(testfile_dir / file, storage_dir / "testfiles")


@sanity_check
def create_log(conf: Config) -> None:
    """Create the directory structure of the log directory.

    Directly instantiate the root logger, so this is not forgotten later.
    """
    log_dir: pathlib.Path = conf["LOG_DIR"]

    recreate_directory(log_dir)

    # TODO does this work as expected? What happens if this is called in another process
    #  than those running later the tests or apache?
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


def setup_logger(name: str, logfile_path: pathlib.Path,
                 log_level: int, syslog_level: int = None,
                 console_log_level: int = None) -> logging.Logger:
    """Configure the :py:mod:`logging` module.

    Since this works hierarchical, it should only be necessary to call this
    once and then every child logger is routed through this configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.debug(f"Logger {name} already initialized.")
        return logger
    logger.propagate = False
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        '[%(asctime)s,%(name)s,%(levelname)s] %(message)s')
    file_handler = logging.FileHandler(str(logfile_path))
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if syslog_level:
        syslog_handler = logging.handlers.SysLogHandler()
        syslog_handler.setLevel(syslog_level)
        syslog_handler.setFormatter(formatter)
        logger.addHandler(syslog_handler)
    if console_log_level:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    logger.debug(f"Configured logger {name}.")
    return logger
