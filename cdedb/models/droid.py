"""Dataclass definitions for API tokens. Such a user is called a 'droid'."""
import abc
import datetime
import re
from dataclasses import dataclass
from functools import lru_cache
from secrets import token_hex
from typing import Any, ClassVar, Optional, Pattern, Type

import cdedb.common.validation.types as vtypes
from cdedb.common import User
from cdedb.common.roles import droid_roles
from cdedb.common.validation.types import TypeMapping
from cdedb.models.common import CdEDataclass


class APIToken(abc.ABC):
    """
    Base class for all api tokens.

    Every token/droid has at least the following attributes:

    * `identity`: A unique string identifying the kind of droid the token belongs to.
        Must match `\\w+`, i.e. be alpha numeric, but may contain `_`.
    * `droid_name`: The droid identity prefixed with the namespace of the droid.
        Simple droids (also called static droids) live in the `static` namespace,
        while complex droids (also called dynamic droids), i.e. those with instances
        that are saved to the database, each have their own namespace.

        Example droid names: `static/resolve`, `orga/<orga_token_id>`.

    All token classes provide a method `format_apitoken` which takes a secret as a
    string and returns a correctly formatted api token with the appropriate droid name.
    Depending on the kind of token, this may be a classmethod.

    For token classes which have instance dependant droid names and thus apitokens,
    there are classmethods available to remove the need to create an instance in
    order to construct a droid name or apitoken for a known token id.
    """
    # Not to be confudes with the `id` of an entity saved to the database.
    identity: ClassVar[str]

    @property
    @abc.abstractmethod
    def droid_name(self) -> str:
        ...

    @staticmethod
    def create_secret() -> str:
        """Provide a central definition for how to create a secret token."""
        return token_hex()

    # Basic pattern for all api token. The droid name will be used to decide how
    #  to validate the given secret.
    apitoken_pattern = re.compile(
        r"CdEDB-(?P<droid_name>\w+/\w+)/(?P<secret>[0-9a-zA-Z\-]+)/")

    @staticmethod
    def _format_apitoken(droid_name: str, secret: str) -> str:
        return f"CdEDB-{droid_name}/{secret}/"


class StaticAPIToken(APIToken):
    """
    Base class for static droids.

    Static droids have no attributes other than their identity and the derived
    droid name.
    """

    @classmethod
    def _droid_name(cls) -> str:
        return f"static/{cls.identity}"

    @property
    def droid_name(self) -> str:
        return self._droid_name()

    @classmethod
    def format_apitoken(cls, secret: str) -> str:
        return cls._format_apitoken(cls._droid_name(), secret)


class ResolveToken(StaticAPIToken):
    identity = "resolve"


class QuickPartialExportToken(StaticAPIToken):
    identity = "quick_partial_export"


@dataclass
class DynamicAPIToken(CdEDataclass, APIToken):
    """
    Base class for dynamic api tokens.

    In addition to the droid identity and droid name, such a dataclass handles storage
    of individual instances of tokens and creation of corresponding User objects.

    Individual types of dynamic api tokens can have additional database fields.
    """

    # Regular fields.
    title: str
    notes: Optional[str]
    expiration: Optional[datetime.datetime]

    # Special logging fields. Are set automatically by session backend.
    ctime: datetime.datetime
    atime: Optional[datetime.datetime]

    def to_database(self) -> dict[str, Any]:
        """Exclude special fields from being set manually."""
        ret = super().to_database()
        del ret['ctime']
        del ret['atime']
        return ret

    @classmethod
    @lru_cache()
    def droid_name_pattern(cls) -> Pattern[str]:
        """Construct a pattern to check if a token belongs to this class."""
        return re.compile(rf"{cls.identity}/(\d+)")

    @classmethod
    def _droid_name(cls, id_: int) -> str:
        return f"{cls.identity}/{id_}"

    @property
    def droid_name(self) -> str:
        return self._droid_name(self.id)

    def format_apitoken(self, secret: str) -> str:
        return self._format_apitoken(self.droid_name, secret)

    def get_user(self) -> User:
        """Return the corresponding user object for this API."""
        return User(
            droid_identity=self.identity,
            droid_token_id=self.id,
            roles=droid_roles(self.identity)
        )

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id=}, {self.title=})"

@dataclass
class OrgaToken(DynamicAPIToken):
    # ID fields. May not be changed.
    event_id: vtypes.ID

    database_table = "event.orga_apitokens"
    identity = "orga"

    @classmethod
    def validation_fields(cls, *, creation: bool) -> tuple[TypeMapping, TypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        # Do not allow changing event id.
        if 'event_id' in optional:
            del optional['event_id']
        return mandatory, optional

    def get_user(self) -> User:
        ret = super().get_user()
        # Additionally set orga info.
        ret.orga = {self.event_id}
        return ret

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id=}, {self.title=}, {self.event_id})"


# Lookup for determining the appropriate static droid for a given droid name.
STATIC_DROIDS: dict[str, Type[StaticAPIToken]] = {
    static_token._droid_name(): static_token  # pylint: disable=protected-access
    for static_token in locals().values()
    if isinstance(static_token, type)
       and issubclass(static_token, StaticAPIToken)
       and static_token is not StaticAPIToken
}

# Lookup for determining the appropriate dynamic droid for a given droid name.
DYNAMIC_DROIDS: dict[Pattern[str], Type[DynamicAPIToken]] = {
    dynamic_token.droid_name_pattern(): dynamic_token
    for dynamic_token in locals().values()
    if isinstance(dynamic_token, type)
       and issubclass(dynamic_token, DynamicAPIToken)
       and dynamic_token is not DynamicAPIToken
}
