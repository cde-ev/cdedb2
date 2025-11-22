"""
This module contains central wrappers of builtin or third-party encryption facilites.

This allows easily switching to different underlying implementations.
"""

import functools
from typing import Protocol, cast, overload

import cryptography.fernet
import passlib.hash

from cdedb.common import BytesLike


def verify_password(password: str, password_hash: str) -> bool:
    """Constant time password verification."""
    return passlib.hash.sha512_crypt.verify(password, password_hash)


def encrypt_password(password: str) -> str:
    """Encrypt a password with a salt and a suitable number of hash rounds."""
    return passlib.hash.sha512_crypt.hash(password)


def generate_encrytion_key() -> bytes:
    """
    Generate an encryption key for symmetric encryption helpers below.

    The returned key is 32 bytes base64-encoded (urlsafe).
    """
    return cryptography.fernet.Fernet.generate_key()


def _encrypt(data: str | bytes | None, *, key: bytes) -> bytes | None:
    """
    Wrapper for encrypting data symmetrically.

    Allows None to passthrough and encodes strings.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    if data is None:
        return None
    if isinstance(data, str):
        data = data.encode("utf-8")
    return cryptography.fernet.Fernet(key).encrypt(data)


class _EncryptProtocol(Protocol):
    """Slightly beefed up annotation for type inferrence purposes."""

    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: str | bytes) -> bytes: ...

    def __call__(self, data: str | bytes | None) -> bytes | None: ...


def get_encrypt(key: bytes) -> _EncryptProtocol:
    """
    Create single argument encryption function based on the given key.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    return cast(_EncryptProtocol, functools.partial(_encrypt, key=key))


def _decrypt(data: BytesLike | None, *, key: bytes) -> bytes | None:
    """
    Wrapper for decrypting data with a symmetric key.

    Reverse of `_encrypt`. Allows None to passthrough, but does not decode to string.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    if data is None:
        return None
    return cryptography.fernet.Fernet(key).decrypt(bytes(data))


def _decrypt_decode(data: BytesLike | None, key: bytes) -> str | None:
    """
    Wrapper for decrypting data to a string with a symmetric key.

    Reverse of `_encrypt`. Allows None to passthrough and decodes result to string.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    ret = _decrypt(data=data, key=key)
    if ret is None:
        return None
    return ret.decode("utf-8")


class _DecryptProtocol(Protocol):
    """Slightly beefed up annotation for type inferrence purposes."""

    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: BytesLike) -> bytes: ...

    def __call__(self, data: BytesLike | None) -> bytes | None: ...


def get_decrypt(key: bytes) -> _DecryptProtocol:
    """
    Create a single argument decryption function based on the given key.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    return cast(_DecryptProtocol, functools.partial(_decrypt, key=key))


class _DecryptDecodeProtocol(Protocol):
    """Slightly beefed up annotation for type inferrence purposes."""

    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: BytesLike) -> str: ...

    def __call__(self, data: BytesLike | None) -> str | None: ...


def get_decrypt_decode(key: bytes) -> _DecryptDecodeProtocol:
    """
    Create a single argument decryption function based on the given key.

    Decodes the result to string.

    The key is of the same format as returned by `generate_encryption_key()`.
    """
    return cast(_DecryptDecodeProtocol, functools.partial(_decrypt_decode, key=key))
