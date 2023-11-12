import pathlib
from typing import Optional

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import (
    AbstractBackend, access, affirm_validation as affirm, internal,
)
from cdedb.common import RequestState, get_hash, unwrap

class AttachmentStorageBackend(AbstractBackend):
    realm = "attachment"

    def __init__(self, dir: pathlib.Path, table: str):
        super().__init__()
        self.table = table
        self.dir = dir

    @classmethod
    def is_admin(self, rs: RequestState) -> bool:
        return False

    @access("anonymous")
    def set(self, rs: RequestState, attachment: bytes) -> str:
        """Store a file for genesis usage. Returns the file hash."""
        attachment = affirm(vtypes.PDFFile, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.dir / myhash
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(attachment)
        return myhash

    @access("anonymous")
    def check(self, rs: RequestState, attachment_hash: str) -> bool:
        """Check whether a genesis attachment with the given hash is available.

        Contrary to `genesis_get_attachment` this does not retrieve it's
        content.
        """
        attachment_hash = affirm(str, attachment_hash)
        path = self.dir / attachment_hash
        return path.is_file()

    @access("anonymous")
    def get(self, rs: RequestState, attachment_hash: str) -> Optional[bytes]:
        """Retrieve a stored genesis attachment."""
        attachment_hash = affirm(str, attachment_hash)
        path = self.dir / attachment_hash
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    @internal
    @access("core_admin")
    def _usage(self, rs: RequestState, attachment_hash: str) -> bool:
        """Check whether a genesis attachment is still referenced in a case."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = f"SELECT COUNT(*) FROM {self.table} WHERE attachment_hash = %s"
        return bool(unwrap(self.query_one(rs, query, (attachment_hash,))))

    @access("core_admin")
    def forget(self, rs: RequestState) -> int:
        """Delete genesis attachments that are no longer in use."""
        ret = 0
        for f in self.dir.iterdir():
            if f.is_file() and not self._usage(rs, f.name):
                f.unlink()
                ret += 1
        return ret
