import pathlib
import subprocess

from cdedb.setup.config import Config
from cdedb.setup.util import sanity_check


def chown(path: pathlib.Path, owner: str) -> None:
    subprocess.run(["sudo", "chown", "--recursive", f"{owner}:{owner}", path],
                   check=True)


def copy(source: pathlib.Path, dest: pathlib.Path) -> None:
    subprocess.run(["sudo", "cp", source, dest], check=True)


def mkdirs(directory: pathlib.Path, owner: str) -> None:
    """Create a directory and its parents and set their owner."""
    subprocess.run(["sudo", "-u", owner, "mkdir", "-p", directory], check=True)


def rmtree(path: pathlib.Path) -> None:
    """Remove the _sub_tree of the given path."""
    # TODO make a decision which parts of the directories should be removed
    #  - including the storage dir itself or excluding?
    subprocess.run(["sudo", "rm", "-rf", "--", path / "*"], check=True)


@sanity_check
def create_storage(conf: Config, owner: str = "www-data") -> None:
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

    # Remove anything left in the storage dir.
    if storage_dir.exists():
        rmtree(storage_dir)
    mkdirs(storage_dir, owner)

    for subdir in subdirs:
        mkdirs(storage_dir / subdir, owner)

    chown(storage_dir, owner)


@sanity_check
def populate_storage(conf: Config, owner: str = "www-data") -> None:
    """Populate the storage directory with sample data."""
    storage_dir: pathlib.Path = conf["STORAGE_DIR"]
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    create_storage(conf, owner)

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

    copy(testfile_dir / foto, storage_dir / "foto")
    copy(testfile_dir / "rechen.pdf", attachment_dir / "1_v1")
    copy(testfile_dir / "kassen.pdf", attachment_dir / "2_v1")
    copy(testfile_dir / "kassen2.pdf", attachment_dir / "2_v3")
    copy(testfile_dir / "kandidaten.pdf", attachment_dir / "3_v1")
    for file in files:
        copy(testfile_dir / file, storage_dir / "testfiles")

    # adjust the owner of the files
    chown(storage_dir, owner)


@sanity_check
def create_log(conf: Config, owner: str = "www-data") -> None:
    """Create the directory structure of the log directory."""
    log_dir: pathlib.Path = conf["LOG_DIR"]

    # Remove anything left in the log dir.
    if log_dir.exists():
        rmtree(log_dir)
    mkdirs(log_dir, owner)
