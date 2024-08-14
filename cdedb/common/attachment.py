import builtins
import pathlib
from typing import Any, Callable, Optional

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import RequestState, get_hash

UsageFunction = Callable[[RequestState, str], bool]

class AttachmentStore:
    """Generic facility for file storage within the cdedb, with instances for each
    class of files to be considered."""

    def __init__(self, dir_: pathlib.Path, type_: builtins.type[Any] = vtypes.PDFFile):
        self._dir = dir_
        self.type = type_

    def store(self, attachment: bytes) -> str:
        """Store a file. Returns the file hash."""
        attachment = affirm(self.type, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.get_path(myhash)
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(attachment)
        return myhash

    def is_available(self, attachment_hash: str) -> bool:
        """Check whether an attachment with the given hash is available.

        Contrary to `get` this does not retrieve it's
        content.
        """
        attachment_hash = affirm(str, attachment_hash)
        return self.get_path(attachment_hash).is_file()

    def get(self, attachment_hash: str) -> Optional[bytes]:
        """Retrieve a stored attachment."""
        # TODO Drop this, if not needed.
        attachment_hash = affirm(str, attachment_hash)
        path = self.get_path(attachment_hash)
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    def get_path(self, attachment_hash: str) -> pathlib.Path:
        """Get path for attachment."""
        return self._dir / attachment_hash

    def forget_one(self, rs: RequestState, usage: UsageFunction, attachment_hash: str
                   ) -> bool:
        "Delete a single attachment if no longer in use"
        path = self.get_path(attachment_hash)
        if path.is_file() and not usage(rs, attachment_hash):
            path.unlink()
            return True
        return False

    def forget(self, rs: RequestState, usage: UsageFunction) -> int:
        """Delete all attachments that are no longer in use."""
        ret = 0
        for f in self._dir.iterdir():
            ret += self.forget_one(rs, usage, f.name)
        return ret
