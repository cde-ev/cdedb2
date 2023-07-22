"""
The API facility is based on three different kinds of objects:

class
    A class, that inherits from either `StaticAPIToken` or `DynamicAPIToken`.
    Accordingly there are two "kinds" of classes: "static" and "dynamic".

    Every such class creates its own API with a unique scope of available endpoints
    and backend methods. The `name` attribute of the class determines the primary role
    of resulting "droids" and the "droid name" used to identify instances of the class.

    Also called "class of droid" or "class of token".

token
    A set of credentials for a "class" of token.

    "static droids" are singletons, i.e. there is exactly one of each class (there is
    no need to instantiate the class). For every static droid, a "secret" may be set
    in the `API_TOKENS` section of the `SecretsConfig` using the "class name" as a key.
    This "secret" is the "token" for that "static droid".

    "dynamic droids" have multiple instances, each with their own secet. Here
    a "token" is a row in a database table. This data is represented by an instance
    of the "droid class" (which is a subclass of `DynamicAPIToken`, which also
    subclasses `CdEDataclass`).

    "token" may also refer to the specially formatted string submitted in the request
    header of a request accessing an API. More accurately this should be called
    "token string".

    Might also be called "API token", "droid token" or "<kind> token",
    e.g. "orga token" for orga droids, "resolve token" for the resolve droid, etc.

droid
    A `User` object for a request performed via the API.

    When a valid API token is provided in the request header, the session backend
    returns an instance of the `User` class for that request. This user object
    and/or the program submitting the request is called a droid. Unless the droid class
    defines such an association, this user object is not assicated with a persona.

    The "kind" defines how the user object is created, often gaining additional
    attributes depending on the specific "kind", like an event id for orga droids.

    "droid" is sometimes used to refer to the all users for a class of droid
    (e.g. "the orga droid" for "all users instances for the 'orga' class of droid".)
    or the entire API of that class (e.g. "an orga droid endpoint").

Other nomenclature:

secret
    A string of cryptographically random alphanumeric characters of
    sufficient length, that serves as authentication for an API.

    Newly created secrets are 64 hexadecimal characters, i.e. 256 Bits of entropy.
    Similar to passwords, secrets are stored only in the form of a salted hash.

    A newly created secret will be displayed to the user exactly once, after which
    it is impossible to discern the secret from the stored hash.

token string
    A specially formatted string that is sent in the request header,
    when using an API. This string includes the "droid name" and the "secret".

class name
    A class attribute of a "class".
    Used in the "droid name" to indentify the class of droid.

    Not to be confused with the actual programmatic name of the class (`<class>.name`
    rather than `<class>.__name__`).

    Examples: "resolve", "quick_partial_export", "orga".

droid name
    A string, identifying exactly one "token" (see above), i.e.
    a static droid (which are singletons) or one instance of a dynamic droid.

    To determine the class of the droid from the droid name use `resolve_droid_name()`.

    Examples: "static/resolve", "orga/<token_id>".

static droid
    A simple API with only one secret set via the `SecretsConfig`.

dynamic droid
    A complex API for which users can create instances ("tokens"),
    each with an individual secret.
"""
import abc
import datetime
import re
from dataclasses import dataclass, field
from functools import lru_cache
from secrets import token_hex
from typing import TYPE_CHECKING, ClassVar, Optional, Pattern, Type, Union

import cdedb.common.validation.types as vtypes
from cdedb.common import User, now
from cdedb.common.roles import droid_roles
from cdedb.common.sorting import Sortkey
from cdedb.common.validation.types import TypeMapping
from cdedb.models.common import CdEDataclass

if TYPE_CHECKING:
    from typing_extensions import Self

    from cdedb.common import CdEDBObject  # pylint:disable=ungrouped-imports


class APIToken(abc.ABC):
    """
    Base class for all API Tokens.

    This baseclass conveniently bundles some constants and static methods useful
    in the context of droid APIs.
    """

    name: ClassVar[str]
    """
    A Unique string identifying the class of droid a token belongs to.

    Must match ``\\w+``, i.e. be alphanumeric, but may contain ``_``.

    Needs to be overridden by subclasses.
    """

    @classmethod
    @lru_cache()
    def get_droid_name_pattern(cls) -> Pattern[str]:
        """
        Return a regex pattern matching all droid names for this class.

        This is a classmethod with a constant return per class, which should be cached.

        The pattern for a static droid may only match exactly one string.

        The pattern for a dynamic droid must have exactly one capture group, which
        captures the token id in that droids namespace. (i.e. the pattern for orga
        droids should match for example ``orga/123`` and capture ``123``).
        """
        raise NotImplementedError

    def get_droid_name(self) -> str:
        """
        Return the droid name prefixed with the namespace for this class of droid.

        For static droids this is a classmethod, for dynamic droids an instance method.

        Static droids live in the `static` namespace, with their name being their
        class name.

        Dynamic droids each have their own namespaces, which is their class name,
        while the name is simply the id of the database entry.
        Dynamic droids also provide a ``_get_droid_name()`` class method which is used
        in ``get_droid_name()`` and takes the id as an argument, so the droid name can
        be determined without needing to create an instance.

        Example droid names: ``static/resolve``, ``orga/<orga_token_id>``.
        """
        raise NotImplementedError

    @staticmethod
    def _get_token_string(droid_name: str, secret: str) -> str:
        """Construct a correctly formatted token string from droid name and secret."""
        return f"CdEDB-{droid_name}/{secret}/"

    def get_token_string(self, secret: str) -> str:
        """
        Return a correctly formatted token string from droid name given secret.

        For static droids this is a classmethod, for dynamic droids an instance method.
        """
        return self._get_token_string(self.get_droid_name(), secret)

    def get_user(self) -> User:
        """Return a `User` object for API requests."""
        raise NotImplementedError

    #: The key of the token string in the request header.
    request_header_key = "X-CdEDB-API-token"

    @staticmethod
    def create_secret() -> str:
        """Provide a central definition for how to create a secret token."""
        return token_hex()

    #: Basic pattern for all api token. The droid name will be used to decide how
    #:  to validate the given secret.
    token_string_pattern = re.compile(
        r"CdEDB-(?P<droid_name>\w+/\w+)/(?P<secret>[0-9a-zA-Z\-]+)/")


class StaticAPIToken(APIToken):
    """
    Base class for static droids. These tokens need not be instantiated.

    Static droids have no attributes other than their name, although subclasses might
    want to override the `get_user` classmethod.

    A static droid API can only be accessed if a secret is set in the `API_TOKENS`
    section of the `SecretsConfig`.
    """
    #: Name of the static droid.
    name: ClassVar[str]

    @classmethod
    @lru_cache
    def get_droid_name_pattern(cls) -> Pattern[str]:
        return re.compile(cls.get_droid_name())

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
    name = "resolve"  #:


class QuickPartialExportToken(StaticAPIToken):
    name = "quick_partial_export"  #:


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
    #: Name of the dynamic droid. Also serves as namespace for droid names.
    name: ClassVar[str]

    # Regular fields.

    title: str  #: Configurable title.
    notes: Optional[str]  #: Configurable notes field.
    etime: datetime.datetime  #: Expiration time. Set once during creation.

    # Special logging fields.

    #: Creation time. Automatically set by event backend on creation.
    ctime: datetime.datetime = field(default_factory=now, init=False)
    #: Revocation time. Automatically set by event backend on revocation.
    rtime: Optional[datetime.datetime] = field(default=None, init=False)
    #: Last access time. Automatically updated by session backend on every request.
    atime: Optional[datetime.datetime] = field(default=None, init=False)

    # Special fields and methods for datacase storage using `CdEDataclass` interface.

    #: Subclasses may define unchangeable fields.
    fixed_fields: ClassVar[tuple[str, ...]] = ('etime',)

    @classmethod
    def from_database(cls, data: "CdEDBObject") -> "Self":
        ctime = data.pop('ctime')
        rtime = data.pop('rtime')
        atime = data.pop('atime')

        ret = super().from_database(data)

        ret.ctime = ctime
        ret.rtime = rtime
        ret.atime = atime

        return ret

    @classmethod
    def validation_fields(cls, *, creation: bool) -> tuple[TypeMapping, TypeMapping]:
        mandatory, optional = super().validation_fields(creation=creation)
        for key in cls.fixed_fields:
            if key in optional:
                del optional[key]
        if 'ctime' in mandatory:
            optional['ctime'] = mandatory['ctime']
            del mandatory['ctime']
        return mandatory, optional

    # Implementations of inherited methods.

    @classmethod
    @lru_cache()
    def get_droid_name_pattern(cls) -> Pattern[str]:
        return re.compile(rf"{cls.name}/(\d+)")

    @classmethod
    def _get_droid_name(cls, id_: int) -> str:
        """Construct the droid name for a known token_id w/o need to instantiate."""
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

    def get_sortkey(self) -> Sortkey:
        return (self.name, self.title, self.ctime, self.id)

    def __lt__(self, other: "DynamicAPIToken") -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.get_sortkey() < other.get_sortkey()


@dataclass
class OrgaToken(DynamicAPIToken):
    """
    OrgaToken(
        id: vtypes.ID, title: str, notes: Optional[str], etime: datetime.datetime,
        ctime: datetime.datetime, rtime: Optional[datetime.datetime],
        atime: Optional[datetime.datetime], event_id: vtypes.ID)

    """
    name = "orga"  #:

    event_id: vtypes.ID  #: ID of the event this token is linked to. May not change.

    # Special attributes for `CdEDatabase` interface.

    #: Fields which may not change.
    fixed_fields = DynamicAPIToken.fixed_fields + ("event_id",)
    #: Table where data for this class of token is stored.
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

    .. code-block:: python

        droid_class, token_id = resolve_droid_name(...)
        if droid_class is None:
            # Invalid droid name.
        if token_id is None:
            # Static droid.
        else:
            # Dynamic droid.
    ..

    Alternatively and if the type of `droid_class` needs to be statically inferred
    more accurately, one can use `issubclass(droid_class, StaticAPIToken)` and
    `is_subclass(droid_class, DynamicAPIToken)`.

    :returns: For an invalid droid name, return `(None, None)`.
        For a matching static droid return `(<static droid class>, None).
        For a matching dynamic droid return `(<dynamic droid class>, <token_id>)`.
    """
    for static_droid in StaticAPIToken.__subclasses__():
        if static_droid.get_droid_name_pattern().fullmatch(droid_name):
            return static_droid, None
    for dynamic_droid in DynamicAPIToken.__subclasses__():
        if m := dynamic_droid.get_droid_name_pattern().fullmatch(droid_name):
            return dynamic_droid, int(m.group(1))
    return None, None
