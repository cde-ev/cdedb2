"""Dataclass definitions for core realm."""

import base64
import dataclasses
import datetime
import re
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Optional

from cryptography.fernet import Fernet

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, now
from cdedb.common.n_ import n_
from cdedb.common.exceptions import CryptographyError
from cdedb.common.parse.util import Accounts
from cdedb.common.sorting import Sortkey
from cdedb.models.common import CdEDataclass

__all__ = ["AnonymousMessageData"]

if TYPE_CHECKING:
    from typing_extensions import Self


@dataclasses.dataclass
class MetaInfo(CdEDataclass):
    database_table = "core.meta_info"

    id: vtypes.ProtoID = dataclasses.field(
        init=False, default=vtypes.ProtoID(1), metadata={'update_exclude': True},
    )

    Finanzvorstand_Name: str | None = None
    Finanzvorstand_Vorname: str | None = None
    Finanzvorstand_Ort: str | None = None
    Finanzvorstand_Adresse_Einzeiler: str | None = None
    Finanzvorstand_Adresse_Zeile2: str | None = None
    Finanzvorstand_Adresse_Zeile3: str | None = None
    Finanzvorstand_Adresse_Zeile4: str | None = None
    Vorstand: str | None = None

    membership_fee_account: Accounts = Accounts.Sozialbank
    lastschrift_account: Accounts = Accounts.Sozialbank

    banner_before_login: str | None = None
    banner_after_login: str | None = None
    banner_genesis: str | None = None
    cde_misc: str | None = None

    lockdown_web: bool = False

    def get_sortkey(self) -> Sortkey:
        return ()


@dataclasses.dataclass
class EmailAddressReport(CdEDataclass):
    address: vtypes.Email
    status: const.EmailStatus
    notes: Optional[str] = None
    # This persona has this address as username.
    user_id: Optional[vtypes.ID] = None
    # This persona has this address as explicit mail address for at least one ml.
    subscriber_id: Optional[vtypes.ID] = None
    # The mailinglists where this address is used as explicit address.
    ml_ids: set[vtypes.ID] = dataclasses.field(default_factory=set)

    database_table = "core.email_states"

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "EmailAddressReport":
        if "ml_ids" in data:
            data["ml_ids"] = set(data["ml_ids"])
        return super().from_database(data)

    @property
    def persona_ids(self) -> set[vtypes.ID]:
        """All persona ids associated with this defect address."""
        ret = set()
        if self.user_id:
            ret.add(self.user_id)
        if self.subscriber_id:
            ret.add(self.subscriber_id)
        return ret

    def get_sortkey(self) -> Sortkey:
        return (self.status, self.address)


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

    def format_secret(self, key: str) -> str:
        return f"{self.message_id}{key}"

    @staticmethod
    def parse_secret(secret: str) -> tuple[str, str]:
        # The message_id has 12 bytes, which is 16 characters in Base64.
        #  The key has 32 bytes, which is 43 characters plus 1 (padding) in Base64.
        pattern = re.compile(r"[a-zA-Z0-9-_=]{60}")
        if pattern.fullmatch(secret):
            return secret[:16], secret[16:]
        else:
            raise ValueError(f"Could not parse secret: {secret}")

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


@dataclasses.dataclass(kw_only=True)
class GenesisCase(CdEDataclass):
    database_table = "core.genesis_cases"

    username: vtypes.Email
    given_names: str
    family_name: str

    realm: vtypes.Realm
    notes: str
    case_status: const.GenesisStati = dataclasses.field(
        metadata={'validation_exclude': True, 'request_exclude': True})
    ctime: datetime.datetime = dataclasses.field(
        metadata={'validation_exclude': True, 'request_exclude': True})
    reviewer: vtypes.ID | None = dataclasses.field(
        default=None, metadata={'validation_exclude': True, 'request_exclude': True})
    persona_id: vtypes.ID | None = dataclasses.field(
        default=None, metadata={'validation_exclude': True, 'request_exclude': True})

    # event fields
    gender: const.Genders | None
    birthday: vtypes.Birthday | None
    telephone: vtypes.Phone | None
    mobile: vtypes.Phone | None
    address_supplement: str | None
    address: str | None
    postal_code: vtypes.PrintableASCII | None
    location: str | None
    country: vtypes.Country | None
    birth_name: str | None

    # cde fields
    attachment_hash: str | None
    pevent_id: int | None
    pcourse_id: int | None

    def get_sortkey(self) -> Sortkey:
        return (self.ctime, self.family_name, self.given_names)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        # Dispatch data to correct dataclass based on realm.
        if (realm := data.get("realm")) is None:
            raise RuntimeError
        if realm == "ml":
            return GenesisCaseMl.from_database(data)
        elif realm == "event":
            return GenesisCaseEvent.from_database(data)
        elif realm == "cde":
            return GenesisCaseCdE.from_database(data)
        else:
            raise NotImplementedError

    def __lt__(self, other: "CdEDataclass") -> bool:
        # enable sorting of all genesis sub classes
        if not isinstance(other, GenesisCase):
            return NotImplemented
        return self._lt_inner(other)

    @classmethod
    def get_available_realms(cls) -> dict[vtypes.Realm, str]:
        return {
            "cde": n_("CdE membership & events"),
            "event": n_("CdE events"),
            "ml": n_("CdE mailinglist"),
        }

    @classmethod
    def get_model_by_realm(cls, realm: str) -> "GenesisCase":
        return {
            "ml": GenesisCaseMl,
            "event": GenesisCaseEvent,
            "cde": GenesisCaseCdE,
        }[realm]

    @classmethod
    def get_relative_admins(cls) -> set[str]:
        return {f"{realm}_admin" for realm in cls.get_available_realms()}

    @property
    def relative_admin(self) -> str:
        return f"{self.realm}_admin"

    @classmethod
    def fields_by_realm(cls) -> dict[str, set[str]]:
        return {
            "ml": {field.name for field in dataclasses.fields(GenesisCaseMl)
                   if field.default is not None},
            "event": {field.name for field in dataclasses.fields(GenesisCaseEvent)
                      if field.default is not None},
            "cde": {field.name for field in dataclasses.fields(GenesisCaseCdE)
                    if field.default is not None},
        }

    @classmethod
    def persona_fields_by_realm(cls) -> dict[str, set[str]]:
        ret = {realm: fields - {"id", "realm", "notes", "case_status", "ctime"}
               for realm, fields in cls.fields_by_realm().items()}
        ret["cde"] -= {"attachment_hash", "pevent_id", "pcourse_id"}
        return ret

    @property
    def persona_fields(self) -> set[str]:
        return self.persona_fields_by_realm()[self.realm]

    @property
    def persona_data(self) -> CdEDBObject:
        return {k: v for k, v in self.as_dict().items() if k in self.persona_fields}


@dataclasses.dataclass(kw_only=True)
class GenesisCaseMl(GenesisCase):
    gender: const.Genders | None = None
    birthday: vtypes.Birthday | None = None
    telephone: vtypes.Phone | None = None
    mobile: vtypes.Phone | None = None
    address_supplement: str | None = None
    address: str | None = None
    postal_code: vtypes.PrintableASCII | None = None
    location: str | None = None
    country: vtypes.Country | None = None
    birth_name: str | None = None

    attachment_hash: str | None = None
    pevent_id: int | None = None
    pcourse_id: int | None = None

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(data)

    @classmethod
    def get_available_realms(cls) -> dict[vtypes.Realm, str]:
        return {
            "ml": n_("CdE mailinglist"),
        }


@dataclasses.dataclass(kw_only=True)
class GenesisCaseEvent(GenesisCase):
    gender: const.Genders
    birthday: vtypes.Birthday
    address: str
    location: str

    attachment_hash: str | None = None
    pevent_id: int | None = None
    pcourse_id: int | None = None

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(data)

    @classmethod
    def get_available_realms(cls) -> dict[vtypes.Realm, str]:
        return {
            "event": n_("CdE events"),
        }


@dataclasses.dataclass(kw_only=True)
class GenesisCaseCdE(GenesisCase):
    gender: const.Genders
    birthday: vtypes.Birthday
    address: str
    location: str

    attachment_hash: str

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(data)

    @classmethod
    def get_available_realms(cls) -> dict[vtypes.Realm, str]:
        return {
            "cde": n_("CdE membership & events"),
        }
