import pathlib
from collections.abc import Callable

import magic

import cdedb.common.validation.types as vtypes
from cdedb.backend.common import affirm_validation as affirm
from cdedb.common import RequestState, get_hash
from cdedb.common.crypt import get_decrypt, get_encrypt

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

    def __init__(self, dir_: pathlib.Path, type_: type[bytes] = vtypes.PDFFile):
        self._dir = dir_
        self.type = type_

    def store(self, attachment: bytes) -> vtypes.Identifier:
        """Validate a file, then store it. Returns the file hash."""
        attachment = affirm(self.type, attachment, file_storage=False)
        myhash: vtypes.Identifier = get_hash(attachment)  # type: ignore[assignment]
        self.get_path(myhash).write_bytes(attachment)
        return myhash

    def is_available(self, attachment_hash: str) -> bool:
        """Check whether an attachment with the given hash is available.

        Contrary to `get` this does not retrieve its content.
        """
        return self.get_path(attachment_hash).is_file()

    def get_mime_type(self, attachment_hash: str) -> str | None:
        """Determine the mime type of a stored attachment."""
        path = self.get_path(attachment_hash)
        if path.is_file():
            return magic.from_buffer(open(path, 'rb').read(2048), mime=True)
        return None

    def get(self, attachment_hash: str) -> bytes | None:
        """Retrieve a stored attachment.

        Only to be used by backend tests, frontend code should stream from path."""
        try:
            return self.get_path(attachment_hash).read_bytes()
        except FileNotFoundError:
            return None

    def get_path(self, attachment_hash: str) -> pathlib.Path:
        """Get path for attachment.

        Takes care of all the path validation."""
        attachment_hash = affirm(vtypes.Identifier, attachment_hash)
        return self._dir / attachment_hash

    def forget_one(
        self, rs: RequestState, usage: UsageFunction, attachment_hash: str
    ) -> bool:
        """Delete a single attachment, if it is no longer in use."""
        if usage(rs, attachment_hash):
            return False
        self.get_path(attachment_hash).unlink(missing_ok=True)
        return True

    def forget(self, rs: RequestState, usage: UsageFunction) -> int:
        """Delete all attachments that are no longer in use."""
        ret = 0
        for f in self._dir.iterdir():
            ret += self.forget_one(rs, usage, f.name)
        return ret


class EncryptedAttachmentStore(AttachmentStore):
    """Storage variant that encrypts files with the given secret.

    Using `store` first validates a file, then encrypts it before writing to disk.
    In order to decrypt a file we need to read it via `get` first.
    This means that streaming files via `get_path` won't work.

    Encryption is salted, so encrypting and storing the same file twice will result
    in different hashes, i.e. the file being duplicated on disk.
    """

    def __init__(
        self, dir_: pathlib.Path, type_: type[bytes] = vtypes.PDFFile, *, secret: bytes
    ):
        super().__init__(dir_=dir_, type_=type_)
        self.encrypt = get_encrypt(secret)
        self.decrypt = get_decrypt(secret)

    def store(self, attachment: bytes) -> vtypes.Identifier:
        """Validate a file, then encrypt and store it. Returns the file hash."""
        attachment = affirm(self.type, attachment, file_storage=False)
        myhash: vtypes.Identifier = get_hash(attachment)  # type: ignore[assignment]
        self.get_path(myhash).write_bytes(self.encrypt(attachment))
        return myhash

    def get(self, attachment_hash: str) -> bytes | None:
        """Retrieve a stored attachment and decrypt it."""
        return self.decrypt(super().get(attachment_hash))

    def get_mime_type(self, attachment_hash: str) -> str | None:
        """Determine the mime type of a stored attachment after decrypting."""
        if content := self.get(attachment_hash):
            return magic.from_buffer(content, mime=True)
        return None
