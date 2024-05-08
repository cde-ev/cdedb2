"""Dataclass definitions for core realm."""

import base64
import dataclasses
import datetime
import re
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Optional

from cryptography.fernet import Fernet

import cdedb.common.validation.types as vtypes
from cdedb.common import now
from cdedb.common.exceptions import CryptographyError
from cdedb.common.sorting import Sortkey
from cdedb.models.common import CdEDataclass

__all__ = ["AnonymousMessageData"]

if TYPE_CHECKING:
    from typing_extensions import Self


@dataclasses.dataclass
class AnonymousMessageData(CdEDataclass):
    database_table = "core.anonymous_messages"
    entity_key = "message_id"

    message_id: vtypes.Base64
    recipient: vtypes.Email
    ctime: datetime.datetime

    encrypted_data: str
    persona_id: Optional[vtypes.ID] = dataclasses.field(init=False, default=None)
    username: Optional[vtypes.Email] = dataclasses.field(init=False, default=None)
    subject: Optional[str] = dataclasses.field(init=False, default=None)

    @staticmethod
    def format_data(persona_id: vtypes.ID, username: vtypes.Email, subject: str) -> str:
        return f"{persona_id} <{username}> {subject}"

    @staticmethod
    def parse_data(data: str) -> tuple[vtypes.ID, vtypes.Email, str]:
        pattern = re.compile(r"(?P<persona_id>\d+) <(?P<username>.+)> (?P<subject>.+)")
        if result := pattern.fullmatch(data):
            return (
                vtypes.ID(vtypes.ProtoID(int(result.group("persona_id")))),
                vtypes.Email(result.group("username")),
                result.group("subject"),
            )
        else:
            raise ValueError(f"Could not parse data: {data}")

    def format_message_id(self, key: str) -> str:
        return f"{self.message_id}{key}"

    @staticmethod
    def parse_message_id(message_id: str) -> tuple[str, str]:
        # The message_id has 12 bytes, which is 16 characters in Base64.
        #  The key has 32 bytes, which is 43 characters plus 1 (padding) in Base64.
        pattern = re.compile(r"[a-zA-Z0-9-_=]{60}")
        if pattern.fullmatch(message_id):
            return message_id[:16], message_id[16:]
        else:
            raise ValueError(f"Could not parse message id: {message_id}")

    @staticmethod
    def create_message_id() -> vtypes.Base64:
        return vtypes.Base64(token_urlsafe(12))

    @staticmethod
    def _encrypt(data: str) -> tuple[str, str]:
        key = Fernet.generate_key()
        encrypted_data = Fernet(key).encrypt(data.encode("utf-8"))
        return (
            base64.b64encode(encrypted_data).decode("ascii"),
            key.decode("ascii"),
        )

    @staticmethod
    def _decrypt(data64: str, key: str) -> str:
        data = base64.b64decode(data64.encode("ascii"))
        return Fernet(key.encode("ascii")).decrypt(data).decode("utf-8")

    @classmethod
    def encrypt(
            cls, recipient: str, persona_id: vtypes.ID, username: vtypes.Email,
            subject: str,
    ) -> tuple["Self", str]:
        data, key = cls._encrypt(cls.format_data(persona_id, username, subject))
        return (
            cls(
                id=vtypes.ProtoID(-1),
                message_id=cls.create_message_id(),
                recipient=vtypes.Email(recipient),
                ctime=now(),
                encrypted_data=data,
            ),
            key,
        )

    def decrypt(self, key: str) -> None:
        try:
            decrypted = self._decrypt(self.encrypted_data, key)
        except Exception as e:
            raise CryptographyError(*e.args) from None
        self.persona_id, self.username, self.subject = self.parse_data(decrypted)

    def rotate(self, key: Optional[str] = None) -> str:
        if self.persona_id is None:
            if key is None:
                raise ValueError("Need decryption key to rotate encryption.")
            self.decrypt(key)
        assert self.persona_id is not None
        assert self.username is not None
        assert self.subject is not None
        data = self.format_data(self.persona_id, self.username, self.subject)
        self.encrypted_data, new_key = self._encrypt(data)
        self.message_id = self.create_message_id()
        return new_key

    def get_sortkey(self) -> Sortkey:
        return self.recipient, self.ctime
