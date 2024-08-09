import pathlib
from typing import Optional

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import RequestState, get_hash, unwrap
from cdedb.database.query import SqlQueryBackend


class AttachmentStore:
    """Generic facility for file storage within the cdedb, with instances for each
    class of files to be considered."""

    def __init__(self, dir: pathlib.Path, table: str, col: str = 'attachment_hash'):
        self.dir = dir
        self.table = table
        self.col = col


    def set(self, attachment: bytes) -> str:
        """Store a file. Returns the file hash."""
        attachment = affirm(vtypes.PDFFile, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.dir / myhash
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(attachment)
        return myhash

    def check(self, attachment_hash: str) -> bool:
        """Check whether an attachment with the given hash is available.

        Contrary to `get` this does not retrieve it's
        content.
        """
        attachment_hash = affirm(str, attachment_hash)
        path = self.dir / attachment_hash
        return path.is_file()

    def get(self, attachment_hash: str) -> Optional[bytes]:
        """Retrieve a stored attachment."""
        attachment_hash = affirm(str, attachment_hash)
        path = self.dir / attachment_hash
        if path.is_file():
            with open(path, 'rb') as f:
                return f.read()
        return None

    def _usage(self, rs: RequestState, backend: SqlQueryBackend, attachment_hash: str) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = f"SELECT COUNT(*) FROM {self.table} WHERE {self.col} = %s"
        return bool(unwrap(backend.query_one(rs, query, (attachment_hash,))))

    def forget(self, rs: RequestState, backend: SqlQueryBackend) -> int:
        """Delete attachments that are no longer in use."""
        ret = 0
        for f in self.dir.iterdir():
            if f.is_file() and not self._usage(rs, backend, f.name):
                f.unlink()
                ret += 1
        return ret
