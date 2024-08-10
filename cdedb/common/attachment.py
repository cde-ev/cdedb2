import abc
import pathlib
from typing import Any, Optional

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import RequestState, get_hash, unwrap
from cdedb.database.query import SqlQueryBackend


class AttachmentStore:
    """Generic facility for file storage within the cdedb, with instances for each
    class of files to be considered."""

    def __init__(self, dir: pathlib.Path, type: type[Any] = vtypes.PDFFile):
        self.dir = dir
        self.type = type

    def store(self, attachment: bytes) -> str:
        """Store a file. Returns the file hash."""
        attachment = affirm(self.type, attachment, file_storage=False)
        myhash = get_hash(attachment)
        path = self.dir / myhash
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

    @abc.abstractmethod
    def _usage(self, rs: RequestState, backend: SqlQueryBackend, attachment_hash: str) -> bool:
        """Check whether an attachment is still referenced."""

    def forget_one(self, rs: RequestState, backend: SqlQueryBackend, attachment_hash: str) -> bool:
        "Delete a single attachment if no longer in use"
        path = self.dir / attachment_hash
        if path.is_file() and not self._usage(rs, backend, attachment_hash):
            path.unlink()
            return True
        return False

    def forget(self, rs: RequestState, backend: SqlQueryBackend) -> int:
        """Delete all attachments that are no longer in use."""
        ret = 0
        for f in self.dir.iterdir():
            ret += self.forget_one(rs, backend, f.name)
        return ret


class GenesisAttachmentStore(AttachmentStore):
    type = vtypes.PDFFile

    def _usage(self, rs: RequestState, backend: SqlQueryBackend,
               attachment_hash: str) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = "SELECT COUNT(*) FROM core.genesis_cases WHERE attachment_hash = %s"
        return bool(unwrap(backend.query_one(rs, query, (attachment_hash,))))

class ProfileFotoStore(AttachmentStore):
    type = vtypes.ProfilePicture

    def _usage(self, rs: RequestState, backend: SqlQueryBackend,
               attachment_hash: str) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = "SELECT COUNT(*) FROM core.personas WHERE attachment_hash = %s"
        return bool(unwrap(backend.query_one(rs, query, (attachment_hash,))))

class AssemblyAttachmentStore(AttachmentStore):
    type = vtypes.PDFFile

    def _usage(self, rs: RequestState, backend: SqlQueryBackend,
               attachment_hash: str) -> bool:
        """Check whether an attachment is still referenced."""
        attachment_hash = affirm(vtypes.RestrictiveIdentifier, attachment_hash)
        query = ("SELECT COUNT(*) FROM assembly.attachment_versions "
                 "WHERE attachment_hash = %s AND dtime IS NOT NULL")
        return bool(unwrap(backend.query_one(rs, query, (attachment_hash,))))

    usage = _usage
