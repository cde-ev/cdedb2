"""Class definitions for api tokens/droids.

A note on nomenclature:

The API facility is based on three different kinds of objects:

- "class": A class, that inherits from either `StaticAPIToken` or `DynamicAPIToken`.
    Accordingly there are two "kinds" of classes: "static" and "dynamic".

    Every such class creates it's own API with a unique scope of available endpoints
    and backend methods. The `name` attribute of the class determines the primary role
    of resulting "droids" and the "droid name" used to identify instances of the class.

    Also called "class of droid" or "class of token.

- "token": A set of credentials for a "class" of token.

    "static droids" are singletons, i.e. there is exactly one of each class (there is
    no need to instantiate the class). For every static droid, a "secret" may be set
    in the `API_TOKENS` section of the `SecretsConfig` using the "class name" as a key.
    This "secret" is the "token" for that "static droid".
    "dynamic" "droids" have multiple instances, each with their own secet. Here
    a "token" is a row in a database table. This data is represented by an instance
    of the "kind" class (which is a subclass of `CdEDataclass`).

    "token" may also refer to the specially formatted string submitted in the request
    header of a request accessing an API. More accurately this should be called
    "token string".

    Might also be called "API token", "droid token", "bot token" or "<kind> token",
    e.g. "orga token" for orga droids, "resolve token" for the resolve droid, etc.

- "droid": A `User` object for a request performed via the API.

    When a valid API token is provided in the request header, the session backend
    returns an instance of the `User` class for that request. This user object
    and/or the program/person submitting the request is called a droid.

    The "kind" defines how the user object is created, often gaining additional
    attributes depending on the specific "kind", like an event id for orga droids.

    "droid" is sometimes used to refer to the all users for a class of droid
    (e.g. "the orga droid" for "all users instances for the 'orga' class of droid".)
    or the entire API of that class (e.g. "an orga droid endpoint").

Other nomenclature:

- "secret": A string of cryptographically random alphanumeric characters of
    sufficient length, that serves as authentication for an API.

    Newly created secrets are 64 hexadecimal characters, i.e. 256 Bits of entropy.
    Similar to passwords, secrets are stored only in the form of a salted hash.

    A newly created secret will be displayed to the user exactly once, after which
    it is impossible to discern the secret from the stored hash.

- "token string": A specially formatted string that is sent in the request header,
    when using an API. This string includes the "droid name" and the "secret".

- "class name": A class attribute of a "class".
    Used in the "droid name" to indentify the class of droid.

    Not to be confused with the actual programmatic name of the class (`<class>.name`
    rather than `<class>.__name__`).

    Examples: "resolve", "quick_partial_export", "orga".

- "droid name": A string, identifying exactly one "token" (see above), i.e.
    a static droid (which are singletons) or one instance of a dynamic droid.

    To determine the class of the droid from the droid name use `resolve_droid_name()`.

    Examples: "static/resolve", "orga/<token_id>".

- "static droid": A simple API with only one secret set via the `SecretsConfig`.

- "dynamic droid": A complex API for which users can create instances ("tokens"),
    each with an individual secret.
"""
import abc
import datetime
import re
from dataclasses import dataclass
from functools import lru_cache
from secrets import token_hex
from typing import Any, ClassVar, Optional, Pattern, Type, Union

import cdedb.common.validation.types as vtypes
from cdedb.common import User
from cdedb.common.roles import droid_roles
from cdedb.common.validation.types import TypeMapping
from cdedb.models.common import CdEDataclass


class APIToken(abc.ABC):
    """
    Base class for all API Tokens.

    Every Token class has at least the following attributes:

    * `name`: A unique string identifying the class of droid the token belongs to.

        Must match `\\w+`, i.e. be alpha numeric, but may contain `_`.

    * `get_droid_name()`: The droid name prefixed with the namespace of the droid.

        For static droids this is a classmethod, for dynamic droids an instance method.

        Static droids live in the `static` namespace, with their name being their
        class name.

        Dynamic droids each have their own namespaces, which is their class name,
        while the name is simply the `id` of the database entry.
        Dynamic droids also provide a `_get_droid_name()` class method which is used
        in `get_droid_name()` and takes the id as an argument, so the droid name can
        be determined without needing to create an instance.

        Example droid names: `static/resolve`, `orga/<orga_token_id>`.

    * `get_token_string()`: A method that takes a secret and returns a correlty
        formatted token string, which includes the droid name and the given secret.

        For static droids this is a classmethod, for dynamic droids an instance method.

    * `get_user()`: A method that creates a `User` object for API requests.

    This baseclass conveniently bundles some constants and static methods useful
    in the context of droid APIs.
    """
    name: ClassVar[str]

    @staticmethod
    def create_secret() -> str:
        """Provide a central definition for how to create a secret token."""
        return token_hex()

    # Basic pattern for all api token. The droid name will be used to decide how
    #  to validate the given secret.
    token_string_pattern = re.compile(
        r"CdEDB-(?P<droid_name>\w+/\w+)/(?P<secret>[0-9a-zA-Z\-]+)/")

    @staticmethod
    def _get_token_string(droid_name: str, secret: str) -> str:
        return f"CdEDB-{droid_name}/{secret}/"

    # The key of the token string in the request header.
    request_header_key = "X-CdEDB-API-token"


class StaticAPIToken(APIToken):
    """
    Base class for static droids.

    Static droids have no attributes other than their name, although subclasses might
    want to override the `get_user` classmethod.

    A static droid API can only be accessed if a secret is set in the `API_TOKENS`
    section of the `SecretsConfig`.
    """

    @classmethod
    def get_droid_name(cls) -> str:
        return f"static/{cls.name}"

    @classmethod
    def get_token_string(cls, secret: str) -> str:
        return cls._get_token_string(cls.get_droid_name(), secret)

    @classmethod
    def get_user(cls) -> User:
        return User(
            droid_class=cls,
            droid_token_id=None,
            roles=droid_roles(cls.name),
        )


class ResolveToken(StaticAPIToken):
    name = "resolve"


class QuickPartialExportToken(StaticAPIToken):
    name = "quick_partial_export"


@dataclass
class DynamicAPIToken(CdEDataclass, APIToken):
    """
    Base class for dynamic droids.

    Since this inherits from `CdEDataclass`, storage and validation are implemented
    mostly automatically.

    Subclasses need to define the class name and the database table the tokens are
    stored in, as well as fields for any additional database columns.

    Fields of dynamic tokens which should not be changeable after creation can be
    specified as `fixed_fields` in the form of a tuple of string.
    """
    # Regular fields.
    title: str
    notes: Optional[str]

    #
    # Special logging fields. Are set automatically by session backend.
    #

    # Creation time.
    ctime: datetime.datetime
    # Expiration time.
    etime: datetime.datetime
    # Revocation time.
    rtime: Optional[datetime.datetime]
    # Last access time.
    atime: Optional[datetime.datetime]

    # Subclasses may define unchangeable fields.
    fixed_fields: ClassVar[tuple[str, ...]] = ('etime',)

    def to_database(self) -> dict[str, Any]:
        """Exclude special fields from being set manually."""
        ret = super().to_database()
        # Creation time is written behind the scenes upon creation.
        del ret['ctime']
        # Revocation time is written behind the scenes upon revocation.
        del ret['rtime']
        # Last access time is written by the session backend on every droid request.
        del ret['atime']
        return ret

    @classmethod
    def validation_fields(cls, *, creation: bool) -> tuple[TypeMapping, TypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        for key in cls.fixed_fields:
            if key in optional:
                del optional[key]
        return mandatory, optional

    @classmethod
    @lru_cache()
    def get_droid_name_pattern(cls) -> Pattern[str]:
        """Construct a pattern to check if a token belongs to this class."""
        return re.compile(rf"{cls.name}/(\d+)")

    @classmethod
    def _get_droid_name(cls, id_: int) -> str:
        return f"{cls.name}/{id_}"

    def get_droid_name(self) -> str:
        return self._get_droid_name(self.id)

    def get_token_string(self, secret: str) -> str:
        return self._get_token_string(self.get_droid_name(), secret)

    def get_user(self) -> User:
        """Return the corresponding user object for this API."""
        return User(
            droid_class=self.__class__,
            droid_token_id=self.id,
            roles=droid_roles(self.name)
        )

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id=}, {self.title=})"


@dataclass
class OrgaToken(DynamicAPIToken):
    # ID fields. May not be changed.
    event_id: vtypes.ID
    fixed_fields = DynamicAPIToken.fixed_fields + ("event_id",)

    # Name of droid class.
    name = "orga"

    database_table = "event.orga_apitokens"

    def get_user(self) -> User:
        ret = super().get_user()
        # Additionally set orga info.
        ret.orga = {self.event_id}
        return ret

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.id=}, {self.title=}, {self.event_id=})"


def resolve_droid_name(
        droid_name: str
) -> Union[
    tuple[Type[StaticAPIToken], None],
    tuple[Type[DynamicAPIToken], int],
    tuple[None, None],
]:
    """Determine the class of token from the given droid name.


    The return should be interpreted similar to this:

    ```
    droid_class, token_id = resolve_droid_name(…)
    if droid_class is None:
        # Invalid droid name.
    if token_id is None:
        # Static droid.
    else:
        # Dynamic droid.
    ```

    Alternatively and if the type of `droid_class` needs to be statically inferred
    more accurately, one can use `issubclass(droid_class, StaticAPIToken)` and
    `is_subclass(droid_class, DynamicAPIToken)`.

    :returns: For an invalid droid name, return `(None, None)`.
        For a matching static droid return `(<static droid class>, None).
        For a matching dynamic droid return `(<dynamic droid class>, <token_id>)`.
    """
    for static_droid in StaticAPIToken.__subclasses__():
        if static_droid.get_droid_name() == droid_name:
            return static_droid, None
    for dynamic_droid in DynamicAPIToken.__subclasses__():
        if m := dynamic_droid.get_droid_name_pattern().fullmatch(droid_name):
            return dynamic_droid, int(m.group(1))
    return None, None
