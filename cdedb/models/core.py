"""Dataclass definitions for core realm."""

import abc
import base64
import copy
import dataclasses
import datetime
import decimal
import re
from enum import auto
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from cryptography.fernet import Fernet

import cdedb.common.validation.types as vtypes
import cdedb.database.constants as const
from cdedb.common import CdEDBObject, now
from cdedb.common.exceptions import CryptographyError
from cdedb.common.n_ import n_
from cdedb.common.parse.util import Accounts
from cdedb.common.sorting import EntitySorter, Sortkey
from cdedb.models.common import AbstractFlag, CdEDataclass, MetaFlag as Meta

if TYPE_CHECKING:
    from typing_extensions import Self


@dataclasses.dataclass
class MetaInfo(CdEDataclass):
    database_table = "core.meta_info"

    id: vtypes.ID = dataclasses.field(
        init=False, default=vtypes.ID(1),
        metadata=Meta.input_exclude.as_dict,
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
    recipient: vtypes.Email = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict)
    ctime: datetime.datetime = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict)

    encrypted_data: str
    persona_id: Optional[vtypes.ID] = dataclasses.field(
        init=False, default=None,
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict
    )
    username: Optional[vtypes.Email] = dataclasses.field(
        init=False, default=None,
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict
    )
    subject: Optional[str] = dataclasses.field(
        init=False, default=None,
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict
    )

    @staticmethod
    def format_data(persona_id: vtypes.ID, username: vtypes.Email, subject: str) -> str:
        return f"{persona_id} <{username}> {subject}"

    @staticmethod
    def parse_data(data: str) -> tuple[vtypes.ID, vtypes.Email, str]:
        pattern = re.compile(r"(?P<persona_id>\d+) <(?P<username>.+)> (?P<subject>.+)")
        if result := pattern.fullmatch(data):
            return (
                vtypes.ID(int(result.group("persona_id"))),
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
                id=vtypes.ID(-1),
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


class PersonaFlag(AbstractFlag):
    """Flags to store special metadata of Persona dataclasses."""
    # This field is exposed for external account creation.
    genesis_exposed = auto()


@dataclasses.dataclass(kw_only=True)
class Persona(CdEDataclass):
    username: vtypes.Email = dataclasses.field(
        metadata=PersonaFlag.genesis_exposed.as_dict)
    # This does not include the ``password_hash`` for security reasons.

    # status flags
    is_active: bool = True
    is_meta_admin: bool = False
    is_core_admin: bool = False
    is_cde_admin: bool = False
    is_finance_admin: bool = False
    is_event_admin: bool = False
    is_ml_admin: bool = False
    is_assembly_admin: bool = False
    is_complaint_admin: bool = False
    is_cde_realm: bool = False
    is_event_realm: bool = False
    is_ml_realm: bool = False
    is_assembly_realm: bool = False
    is_cdelokal_admin: bool = False
    is_auditor: bool = False
    is_member: bool = False
    is_searchable: bool = False
    is_archived: bool = False
    is_purged: bool = False

    title: str | None = None
    nickname: str | None = None
    legal_given_names: str | None = None
    given_names: str = dataclasses.field(metadata=PersonaFlag.genesis_exposed.as_dict)
    family_name: str = dataclasses.field(metadata=PersonaFlag.genesis_exposed.as_dict)
    name_supplement: str | None = None
    show_legal_given_names: bool = False

    # admin notes
    notes: str | None = None

    # TODO implement this properly
    def get_sortkey(self) -> Sortkey:
        return EntitySorter.persona(self.as_dict())


@dataclasses.dataclass(kw_only=True)
class MlPersona(Persona):
    ...


@dataclasses.dataclass(kw_only=True)
class EventPersona(MlPersona):
    gender: const.Genders = dataclasses.field(
        metadata=PersonaFlag.genesis_exposed.as_dict)
    birthday: vtypes.Birthday = dataclasses.field(
        metadata=PersonaFlag.genesis_exposed.as_dict)
    telephone: vtypes.Phone | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    mobile: vtypes.Phone | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    address_supplement: str | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    # TODO make mandatory?
    # mandatory during genesis cases, but not enforced otherwise. Since this is currenlty only used by genesis,
    # its mandatory here.
    address: str = dataclasses.field(metadata=PersonaFlag.genesis_exposed.as_dict)
    postal_code: vtypes.PrintableASCII | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    # TODO make mandatory?
    # mandatory during genesis cases, but not enforced otherwise. Since this is currenlty only used by genesis,
    # its mandatory here.
    location: str = dataclasses.field(metadata=PersonaFlag.genesis_exposed.as_dict)
    # TODO make mandatory?
    country: vtypes.Country | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    pronouns: str | None = None
    pronouns_nametag: bool = False
    pronouns_profile: bool = False


@dataclasses.dataclass(kw_only=True)
class CdEPersona(EventPersona):
    show_address: bool = True
    show_address2: bool = True
    address_supplement2: str | None = None
    address2: str | None = None
    postal_code2: vtypes.PrintableASCII | None = None
    location2: str | None = None
    country2: vtypes.Country | None = None
    weblink: str | None = None
    specialisation: str | None = None
    affiliation: str | None = None
    timeline: str | None = None
    interests: str | None = None
    free_form: str | None = None
    balance: decimal.Decimal = decimal.Decimal()
    decided_search: bool = False
    trial_member: bool = False
    bub_search: bool = False
    foto: str | None = None
    paper_expuls: bool = True
    birth_name: str | None = dataclasses.field(
        default=None, metadata=PersonaFlag.genesis_exposed.as_dict)
    donation: decimal.Decimal = decimal.Decimal()
    honorary_member: bool = False


@dataclasses.dataclass(kw_only=True)
class GenesisCase(CdEDataclass):
    database_table = "core.genesis_cases"

    # only changable via separate frontend endpoint
    realm: vtypes.Realm = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)
    notes: str
    status: const.GenesisStati = dataclasses.field(
        metadata=Meta.input_exclude.as_dict)
    ctime: datetime.datetime = dataclasses.field(
        metadata=Meta.input_exclude.as_dict)
    reviewer: vtypes.ID | None = dataclasses.field(
        default=None, metadata=Meta.input_exclude.as_dict)
    persona_id: vtypes.ID | None = dataclasses.field(
        default=None, metadata=Meta.input_exclude.as_dict)

    persona: Persona = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict)

    # further information tied to the genesis case but not to persona dataclass
    attachment_hash: str | None = dataclasses.field(
        metadata=Meta.input_update_exclude.as_dict)
    pevent_id: int | None
    pcourse_id: int | None

    @classmethod
    def get_persona_class(cls) -> type[Persona]:
        # extracts the persona class from its type annotation,
        # since this is static information
        return {field.type for field in dataclasses.fields(cls)
                if field.name == "persona"}.pop()  # type: ignore[return-value]

    @classmethod
    def dataclass_fields(
        cls, *, only_meta: bool = False, only_persona: bool = False
    ) -> tuple[dataclasses.Field[Any], ...]:
        if only_meta and only_persona:
            raise RuntimeError

        meta_fields = [field for field in dataclasses.fields(cls)]
        if only_meta:
            return tuple(meta_fields)

        persona_class = cls.get_persona_class()
        # use always CdE persona as reference, to make sure we fetch
        # all data from the database and from requests
        if cls == GenesisCase:
            persona_class = CdEPersona
        persona_fields = [field for field in dataclasses.fields(persona_class)
                          if PersonaFlag.genesis_exposed.in_field(field)]
        if only_persona:
            return tuple(persona_fields)

        return tuple([*meta_fields, *persona_fields])

    @classmethod
    def database_fields(
        cls, *, only_meta: bool = False, only_persona: bool = False
    ) -> list[str]:
        if only_meta and only_persona:
            raise RuntimeError
        ret = super().database_fields()
        if only_meta:
            database_fields = {field.name for field in cls.dataclass_fields(only_meta=True)}
            ret = [field for field in ret if field in database_fields]
        if only_persona:
            persona_fields = {field.name for field in cls.dataclass_fields(only_persona=True)}
            ret = [field for field in ret if field in persona_fields]
        return ret

    def get_sortkey(self) -> Sortkey:
        return (self.ctime, *self.persona.get_sortkey())

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        realm = data.get("realm")
        # Dispatch data to correct dataclass based on realm.
        if realm == "ml":
            return GenesisCaseMl.from_database(data)  # type: ignore[return-value]
        elif realm == "event":
            return GenesisCaseEvent.from_database(data)  # type: ignore[return-value]
        elif realm == "cde":
            return GenesisCaseCdE.from_database(data)  # type: ignore[return-value]
        else:
            raise RuntimeError

    def __lt__(self, other: "CdEDataclass") -> bool:
        # enable sorting of all genesis sub classes
        if not isinstance(other, GenesisCase):
            return NotImplemented
        return self._lt_inner(other)

    available_realms: ClassVar[dict[vtypes.Realm, str]] = {
        vtypes.Realm("cde"): n_("CdE membership & events"),
        vtypes.Realm("event"): n_("CdE events"),
        vtypes.Realm("ml"): n_("CdE mailinglist"),
    }

    @classmethod
    def get_model_by_realm(cls, realm: str) -> type["GenesisCase"]:
        return {
            "ml": GenesisCaseMl,
            "event": GenesisCaseEvent,
            "cde": GenesisCaseCdE,
        }[realm]

    @property
    def model(self) -> type["GenesisCase"]:
        return self.get_model_by_realm(self.realm)

    all_admins: ClassVar[set[str]] = {
        f"{realm}_admin" for realm in available_realms
    }

    @property
    def relative_admin(self) -> str:
        return f"{self.realm}_admin"

    def get_persona_upgrade(self) -> dict[str, Any]:
        """Dict to upgrade an existing persona as the final stage of a genesis case."""
        keys = {field.name for field in self.dataclass_fields(only_persona=True)}
        keys -= {'username'}
        proto_persona = self.persona.as_dict()
        ret = {key: proto_persona[key] for key in keys if proto_persona[key]}
        ret['id'] = self.persona_id
        return ret

    @abc.abstractmethod
    def get_persona_creation(self) -> Persona:
        """Dataclass to create a new persona as the final stage of a genesis case."""
        ...


@dataclasses.dataclass(kw_only=True)
class GenesisCaseMl(GenesisCase):
    persona: MlPersona = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        meta_data = {k: v for k, v in data.items() if k in cls.database_fields(only_meta=True)}
        persona_data = {k: v for k, v in data.items() if k in cls.database_fields(only_persona=True)}
        persona_data["id"] = None
        meta_data["persona"] = cls.get_persona_class().from_database(persona_data)
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(meta_data)

    def get_persona_creation(self) -> MlPersona:
        persona = copy.deepcopy(self.persona)
        persona.is_ml_realm = True
        return persona


@dataclasses.dataclass(kw_only=True)
class GenesisCaseEvent(GenesisCase):
    persona: EventPersona = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        meta_data = {k: v for k, v in data.items() if k in cls.database_fields(only_meta=True)}
        persona_data = {k: v for k, v in data.items() if k in cls.database_fields(only_persona=True)}
        persona_data["id"] = None
        meta_data["persona"] = cls.get_persona_class().from_database(persona_data)
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(meta_data)

    def get_persona_creation(self) -> EventPersona:
        persona = copy.deepcopy(self.persona)
        persona.is_ml_realm = True
        persona.is_event_realm = True
        return persona


@dataclasses.dataclass(kw_only=True)
class GenesisCaseCdE(GenesisCase):
    persona: CdEPersona = dataclasses.field(
        metadata=(Meta.input_exclude | Meta.database_exclude).as_dict)
    attachment_hash: str = dataclasses.field(metadata=Meta.input_update_exclude.as_dict)

    @classmethod
    def from_database(cls, data: CdEDBObject) -> "Self":
        meta_data = {k: v for k, v in data.items() if k in cls.database_fields(only_meta=True)}
        persona_data = {k: v for k, v in data.items() if k in cls.database_fields(only_persona=True)}
        persona_data["id"] = None
        meta_data["persona"] = cls.get_persona_class().from_database(persona_data)
        # Skip the dataclass dispatching in GenesisCase.
        return super(GenesisCase, cls).from_database(meta_data)

    def get_persona_creation(self) -> EventPersona:
        persona = copy.deepcopy(self.persona)
        persona.is_ml_realm = True
        persona.is_event_realm = True
        persona.is_assembly_realm = True
        persona.is_cde_realm = True
        persona.is_member = True
        persona.trial_member = True
        return persona
