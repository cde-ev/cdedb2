"""Set up the file system related stuff, like upload-storage, loggers and log dirs."""
import json
import os
import pathlib
import shutil
from collections.abc import Collection

from cdedb.backend.entity_keeper import EntityKeeper
from cdedb.cli.util import (
    SAMPLE_DATA_JSON, sanity_check, sanity_check_production, switch_user,
)
from cdedb.config import Config, SecretsConfig, get_configpath


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

    foto = ("e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425"
            "a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9")
    genesis = ("71186e9b6f29e6c984b85a59bfb644a771dc58d286dcb40e5768d15258c0a8f1dac0"
               "91feb7943d2d2fd4b038459585e8e42edaf3f493fff1c6c99d12b5f2d93d")
    files = (
        "picture.pdf",  # core: genesis request file
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

    testfile_dir = repo_path / "tests" / "ancillary_files"
    attachment_dir = storage_dir / "assembly_attachment"
    genesis_dir = storage_dir / "genesis_attachment"

    shutil.copy(testfile_dir / foto, storage_dir / "foto")
    shutil.copy(testfile_dir / "rechen.pdf", attachment_dir / "1_v1")
    shutil.copy(testfile_dir / "kassen.pdf", attachment_dir / "2_v1")
    shutil.copy(testfile_dir / "kassen2.pdf", attachment_dir / "2_v3")
    shutil.copy(testfile_dir / "kandidaten.pdf", attachment_dir / "3_v1")
    shutil.copy(testfile_dir / "picture.pdf", genesis_dir / genesis)
    for file in files:
        shutil.copy(testfile_dir / file, storage_dir / "testfiles")


@sanity_check_production
def populate_event_keeper(conf: Config, event_ids: Collection[int]) -> None:
    """Initialize the event keeper git for the given events.

    This is needed for instances populated with sample data, and for offline instances.
    """
    keeper = EntityKeeper(conf, 'event_keeper')
    for event_id in event_ids:
        keeper.init(event_id)
        keeper.commit(event_id, "", "Initialer Commit.")


@sanity_check
def populate_sample_event_keepers(conf: Config) -> None:
    """Initialize the event keeper git for all events from the sample data."""
    with open(conf["REPOSITORY_PATH"] / SAMPLE_DATA_JSON, encoding="UTF-8") as f:
        sample_data = json.load(f)
    max_event_id = len(sample_data.get('event.events'))
    populate_event_keeper(conf, range(1, max_event_id + 1))


@sanity_check
def create_log(conf: Config) -> None:
    """Create the directory structure of the log directory.

    This will delete the whole content of the log directory, including all log files.
    """
    log_dir: pathlib.Path = conf["LOG_DIR"]

    _recreate_directory(log_dir)


@sanity_check
def reset_config(conf: Config) -> tuple[Config, SecretsConfig]:
    """Replace the current config file with the sample config."""
    sample_config_path: pathlib.Path = (
        conf["REPOSITORY_PATH"] / "related/auto-build/files/stage3/localconfig.py")
    config_path = get_configpath()

    # there is obviously nothing to do
    if sample_config_path.samefile(config_path):
        return Config(), SecretsConfig()

    config_path.unlink()
    shutil.copy(sample_config_path, config_path)
    shutil.chown(config_path, "cdedb", "cdedb")
    return Config(), SecretsConfig()
