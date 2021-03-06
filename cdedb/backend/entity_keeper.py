#!/usr/bin/env python3

"""
The `EntityKeeper` is a wrapper around a git repository containing a set of files
representing an entity at a specific time.

It takes care of initializing, commiting to and deleting a git repository, which is
furthermore set up as a read-only git server. Remote access management is delegated
to apache or similar.

Depending on the specific use case, one may choose to use one EntityKeeper for each
individual entity, or for all entities of a specific type.
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Union

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import PathLike, setup_logger
from cdedb.config import Config


class EntityKeeper:
    def __init__(self, conf: Config, directory: PathLike):
        """This specifies the base directory where the individual entity repositories
        will be located."""
        self.conf = conf
        self._dir = self.conf['STORAGE_DIR'] / directory

        # Initialize logger.
        logger_name = "cdedb.backend.entitykeeper"
        setup_logger(
            logger_name, self.conf["LOG_DIR"] / "cdedb-backend-keeper.log",
            self.conf["LOG_LEVEL"], syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.logger = logging.getLogger(logger_name)
        self.logger.debug(f"Instantiated {self} with configpath {conf._configpath}.")

    def _run(self, args: List[Union[Path, str, bytes]], cwd: Optional[Path] = None,
             check: Optional[bool] = True) -> subprocess.CompletedProcess[bytes]:
        """Custom wrapper of subprocess.run to include proper logging.

        :param check: If True, raise on error. If False, log an error.
            If None, ignore error."""
        # Delay check to ensure logging
        completed = subprocess.run(args, cwd=cwd, check=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        msg = completed.stdout or ""
        if check is not None and completed.returncode != 0:
            self.logger.error("Git error performing command %s in directory %s: %s",
                              args, cwd, msg)
        else:
            self.logger.debug("Git output performing command %s in directory %s: %s",
                              args, cwd, msg)
        if check:
            # Now, raise the check extension
            completed.check_returncode()
        return completed

    def init(self, entity_id: int) -> "EntityKeeper":
        """Actually initialize the repository.

        This takes care of all the dirty work regarding git configuration and
        preparation of a basic git server. Fails if the directory does already exist.
        """
        # Be double-safe against directory transversal
        entity_id = affirm(int, entity_id)
        full_dir = self._dir / str(entity_id)

        full_dir.mkdir()
        # See https://git-scm.com/book/en/v2/Git-on-the-Server-The-Protocols
        self._run(["git", "init", "-b", "master"], cwd=full_dir)
        self._run(["git", "config", "user.name", "CdE-Datenbank"], cwd=full_dir)
        self._run(["git", "config", "user.email", "datenbank@cde-ev.de"], cwd=full_dir)
        shutil.move(full_dir / ".git/hooks/post-update.sample",
                    full_dir / ".git/hooks/post-update")
        # Additionally run post-commit since we commit on the repository itself
        shutil.copy(full_dir / ".git/hooks/post-update",
                    full_dir / ".git/hooks/post-commit")
        self._run(["chmod", "a+x", ".git/hooks/post-update", ".git/hooks/post-commit"],
                  cwd=full_dir)
        self._run(["git", "update-server-info"], cwd=full_dir)

        return self

    def delete(self, entity_id: int) -> None:
        """Irreversibly delete entity keeper repostory."""
        # Be double-safe against directory transversal
        entity_id = affirm(int, entity_id)
        try:
            shutil.rmtree(self._dir / str(entity_id))
        except FileNotFoundError:
            # We do not care if the entity keeper has been deleted yet.
            # For example, this is the case for deleting an archived event.
            pass

    def commit(self, entity_id: int, file_text: str, commit_msg: str,
               author_name: str = "", author_email: str = "", *,
               may_drop: bool = True) -> Optional[subprocess.CompletedProcess[bytes]]:
        """Commit a single file representing an entity to a git repository.

        In contrast to its friends, we allow some wiggle room for errors here right now
        and just log them instead of aborting. Once we are reasonably sure there is
        rarely interference, we may revisit this.

        :param may_drop: If true, this commit may be dropped if empty. If false, an
            empty commit is made if needed. May not be true for initial commit.
        :returns: Representation of the finished commit, if one was done, else None
        """
        entity_id = affirm(int, entity_id)
        file_text = affirm(vtypes.StringType, file_text)
        commit_msg = affirm(str, commit_msg)
        full_dir = self._dir / str(entity_id)
        filename = f"{entity_id}.json"

        # Write to a file in a temporary directory, in order to be thread safe.
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            (td / filename).write_text(file_text)
            # Declare the temporary directory to be the working tree, and specify the
            # actual git directory.
            self._run(["git", f"--work-tree={td}", "add", td / filename], cwd=full_dir)
            # Then commit everything as if we were in the repository directory.
            commit: List[Union[PathLike, bytes]]
            commit = ["git", "-C", full_dir, "commit", "-m", commit_msg.encode("utf8")]
            if author_name or author_email:
                commit.append("--author")
                commit.append(f"{author_name} <{author_email}>".encode("utf8"))

            # Take care of potential empty commits
            if may_drop:
                # git diff-index reports whether the working directory is clean using
                # its exit code. If the dir is clean it returns 0, and 1 otherwise.
                # Does not work for the initial commit since HEAD is not defined yet.
                completed = self._run(
                    ["git", f"--work-tree={td}", "diff-index", "--exit-code", "HEAD"],
                    cwd=full_dir, check=None)
                if completed.returncode == 0:
                    return None
            if not may_drop:
                commit.append("--allow-empty")

            # Do not check here such that an error does not drag the whole request down
            # In particular, this is expected for empty commits.
            return self._run(commit, check=False)
