"""Set up the file system related stuff, like upload-storage, loggers and log dirs."""

import json
import os
import pathlib
import shutil
from collections.abc import Collection

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.complaint import ComplaintBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.entity_keeper import EntityKeeper
from cdedb.cli.util import (
    SAMPLE_DATA_JSON,
    sanity_check,
    sanity_check_production,
    switch_user,
)
from cdedb.config import Config


def _recreate_directory(directory: pathlib.Path) -> None:
    """Create the given directory, or remove its content if it already exists.

    Since the right to create or delete a directory is determined by its parent and not
    by the directory itself, this is a bit tricky. Therefore, this also does some error
    detection about missing permissions.
    """
    # Create the directory if it does not exist
    if not directory.exists():
        # First try as current user and only then as root
        try:
            directory.mkdir(parents=True)
        except PermissionError:
            with switch_user("root"):
                directory.mkdir(parents=True)

    # Chown the directory to the effective user
    if (
        directory.stat().st_uid != os.geteuid()
        or directory.stat().st_gid != os.getegid()
    ):
        euid = os.geteuid()
        egid = os.getegid()
        # First try without root if CAP_CHOWN is given
        try:
            shutil.chown(directory, euid, egid)
        except PermissionError:
            with switch_user("root"):
                shutil.chown(directory, euid, egid)

    # Remove the content of the directory
    for path in directory.iterdir():
        if path.is_dir():
            # Direct entries can always be removed but subdirectories belonging
            # to the previous owner might require elevated permissions
            try:
                shutil.rmtree(path)
            except PermissionError:
                with switch_user("root"):
                    shutil.rmtree(path)
        else:
            path.unlink()


@sanity_check
def create_storage(conf: Config) -> None:
    """Create the directory structure of the storage directory.

    This will delete the whole content of the storage directory.
    """
    storage_dir: pathlib.Path = conf["STORAGE_DIR"]

    subdirs = (
        "foto",  # core: profile fotos
        "genesis_attachment",  # core: genesis attachments
        "minor_form",  # event: minor forms
        "event_keeper",  # event: git repositories of event keeper
        "mailman_templates",  # ml: mailman message templates
        "ballot_result",  # assembly: ballot result files
        "assembly_attachment",  # assembly: attachment files
        "testfiles",  # tests: all testfiles
        "complaint_attachment",  # complaint: encrypted attachment files
    )

    _recreate_directory(storage_dir)
    for subdir in subdirs:
        (storage_dir / subdir).mkdir()


@sanity_check
def populate_storage(conf: Config) -> None:
    """Populate the storage directory with sample data."""
    storage_dir: pathlib.Path = conf["STORAGE_DIR"]
    repo_path: pathlib.Path = conf['REPOSITORY_PATH']

    if not storage_dir.is_dir():
        raise RuntimeError("Create storage before you populate it.")

    foto = "e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9"
    genesis = "picture.pdf"
    files = (
        "picture.pdf",  # core: genesis request file
        "picture.png",  # core: profile foto
        "picture.jpg",  # core: profile foto
        "batch_admission.csv",  # cde: sample input for batch admission
        "sepapain.xml",  # cde: example result of sepapain lastschrift file
        "sepapain_single.xml",  # cde: example result of sepapain lastschrift file
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
        "case_1.txt",  # complaint: sample case export
    )

    testfile_dir = repo_path / "tests" / "ancillary_files"

    core = CoreBackend()
    core._foto_store.store((testfile_dir / foto).read_bytes())
    core._genesis_attachment_store.store((testfile_dir / genesis).read_bytes())

    complaint = ComplaintBackend()
    complaint._attachment_store.store((testfile_dir / "form.pdf").read_bytes())

    assembly = AssemblyBackend()
    for filename in ("rechen.pdf", "kassen.pdf", "kassen2.pdf", "kandidaten.pdf"):
        with open(testfile_dir / filename, "rb") as f:
            assembly._attachment_store.store(f.read())

    for file in files:
        shutil.copy(testfile_dir / file, storage_dir / "testfiles")


@sanity_check_production
def populate_event_keeper(conf: Config, event_ids: Collection[int]) -> None:
    """Initialize the event keeper git for the given events.

    This is needed for instances populated with sample data, and for offline instances.
    """
    keeper = EntityKeeper(conf, 'event_keeper', log_keys=[], log_timestamp_key="")
    for event_id in event_ids:
        keeper.init(event_id, exists_ok=True)
        keeper.commit(event_id, "", "Initialer Commit.")


@sanity_check
def populate_sample_event_keepers(conf: Config) -> None:
    """Initialize the event keeper git for all events from the sample data."""
    with open(conf["REPOSITORY_PATH"] / SAMPLE_DATA_JSON, encoding="UTF-8") as f:
        sample_data = json.load(f)
    max_event_id = len(sample_data.get('event.events'))
    populate_event_keeper(conf, range(1, max_event_id + 1))


@sanity_check
def reset_config(conf: Config) -> None:
    """Replace the current config file with the sample config."""
    config_paths = conf.get_config_paths()

    for path in config_paths:
        # Overwrite config with an empty file. (i.e. delete any overrides).
        path.write_bytes(b"")
        shutil.chown(path, "cdedb", "cdedb")
