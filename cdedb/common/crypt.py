"""
This module contains central wrappers of builtin or third-party encryption facilites.

This allows easily switching to different underlying implementations.
"""

import functools
from typing import Protocol, cast, overload

import cryptography.fernet
import passlib

from cdedb.common import BytesLike


def verify_password(password: str, password_hash: str) -> bool:
    return passlib.hash.sha512_crypt.verify(password, password_hash)


def encrypt_password(password: str) -> str:
    return passlib.hash.sha512_crypt.hash(password)


def generate_encrytion_key() -> bytes:
    return cryptography.fernet.Fernet.generate_key()


def _encrypt(data: str | bytes | None, *, key: bytes) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, str):
        data = data.encode("utf-8")
    return cryptography.fernet.Fernet(key).encrypt(data)


class _EncryptProtocol(Protocol):
    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: str | bytes) -> bytes: ...

    def __call__(self, data: str | bytes | None) -> bytes | None: ...


def get_encrypt(key: bytes) -> _EncryptProtocol:
    return cast(_EncryptProtocol, functools.partial(_encrypt, key=key))


def _decrypt(data: BytesLike | None, *, key: bytes) -> bytes | None:
    if data is None:
        return None
    return cryptography.fernet.Fernet(key).decrypt(bytes(data))


def _decrypt_decode(data: BytesLike | None, key: bytes) -> str | None:
    ret = _decrypt(data=data, key=key)
    if ret is None:
        return None
    return ret.decode("utf-8")


class _DecryptProtocol(Protocol):
    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: BytesLike) -> bytes: ...

    def __call__(self, data: BytesLike | None) -> bytes | None: ...


def get_decrypt(key: bytes) -> _DecryptProtocol:
    return cast(_DecryptProtocol, functools.partial(_decrypt, key=key))


class _DecryptDecodeProtocol(Protocol):
    @overload
    def __call__(self, data: None) -> None: ...

    @overload
    def __call__(self, data: BytesLike) -> str: ...

    def __call__(self, data: BytesLike | None) -> str | None: ...


def get_decrypt_decode(key: bytes) -> _DecryptDecodeProtocol:
    return cast(_DecryptDecodeProtocol, functools.partial(_decrypt_decode, key=key))
