# pylint: disable=missing-module-docstring

import builtins
import pathlib
from typing import Any, Callable, Optional

import magic

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import RequestState, get_hash

UsageFunction = Callable[[RequestState, str], bool]


class AttachmentStore:
    """Generic facility for hash-based file storage within the cdedb.

    There are two patterns to use this facility:
    * low-level: Direct usage of `store` by the frontend to write file, without caching
    * high-level: Usage of :func:`~cdedb.frontend.common.locate_or_store_attachment`
        to provide caching functionality by keeping hash and original filename reference
        to previously uploaded files within `rs.values['attachment_hash']` and
        `rs.values['attachment_filename']`.

    In any case, the file is not retrieved from the backend, but its path streamed by
    the frontend. Therefore, per-file access restrictions must be enforced there.
    The backend generally presumes the frontend has deposited the attachment and only
    affirms that it `is_available`.
    """
    def __init__(self, dir_: pathlib.Path, type_: builtins.type[Any] = vtypes.PDFFile):
        self._dir = dir_
        self.type = type_

    def store(self, attachment: bytes) -> vtypes.Identifier:
        """Store a file. Returns the file hash."""
        attachment = affirm(self.type, attachment, file_storage=False)
        myhash: vtypes.Identifier = get_hash(attachment)  # type: ignore[assignment]
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
        return self.get_path(attachment_hash).is_file()

    def get_mime_type(self, attachment_hash: str) -> Optional[str]:
        """Determine the mime type of a stored attachment."""
        path = self.get_path(attachment_hash)
        if path.is_file():
            return magic.from_buffer(open(path, 'rb').read(2048), mime=True)
        return None

    def get(self, attachment_hash: str) -> Optional[bytes]:
        """Retrieve a stored attachment.

        Only to be used by backend tests, frontend code should stream from path."""
        path = self.get_path(attachment_hash)
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    def get_path(self, attachment_hash: str) -> pathlib.Path:
        """Get path for attachment.

        Takes care of all the path validation."""
        attachment_hash = affirm(vtypes.Identifier, attachment_hash)
        return self._dir / attachment_hash

    def forget_one(self, rs: RequestState, usage: UsageFunction, attachment_hash: str,
                   ) -> bool:
        "Delete a single attachment, if it is no longer in use."
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
