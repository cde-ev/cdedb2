#!/usr/bin/env python3

"""Global utility functions."""
import collections
import collections.abc
import datetime
import decimal
import enum
import functools
import gettext  # pylint: disable=unused-import
import hashlib
import hmac
import itertools
import json
import logging
import logging.handlers
import pathlib
import re
import string
import sys
import zoneinfo
from collections.abc import Collection, Iterable, Mapping, MutableMapping, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)

import phonenumbers
import psycopg2.extras
import werkzeug
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.routing
from schulze_condorcet.types import Candidate

import cdedb.database.constants as const
from cdedb.common.exceptions import PrivilegeError, ValidationWarning
from cdedb.common.n_ import n_
from cdedb.common.roles import roles_to_admin_views
from cdedb.config import LazyConfig
from cdedb.database.connection import ConnectionContainer
from cdedb.uncommon.intenum import CdEIntEnum

if TYPE_CHECKING:
    import cdedb.models.event as models_event
    from cdedb.models.event import CdEDataclassMap

_LOGGER = logging.getLogger(__name__)
_CONFIG = LazyConfig()

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = dict[str, Any]
if TYPE_CHECKING:
    CdEDBMultiDict = werkzeug.datastructures.MultiDict[str, Any]
    from cdedb.models.droid import APIToken
else:
    CdEDBMultiDict = werkzeug.datastructures.MultiDict

# Map of pseudo objects, indexed by their id, as returned by
# `get_events`, event["parts"], etc.

CdEDBObjectMap = dict[int, CdEDBObject]

# Same as above, but we also allow negative ints (for creation, not reflected
# in the type] and None (for deletion). Used in `_set_tracks` and partial
# import diff.
CdEDBOptionalMap = dict[int, Optional[CdEDBObject]]

# An integer with special semantics. Positive return values indicate success,
# a return of zero signals an error, a negative return value indicates some
# special case like a change pending review.
DefaultReturnCode = int

# Return value for `delete_foo_blockers` part of the deletion interface.
# The key specifies the kind of blocker, the value is a list of blocking ids.
# For some blockers the value might have a different type, mostly when that
# blocker blocks deletion without the option to cascadingly delete.
DeletionBlockers = dict[str, list[int]]

# Pseudo error objects used to display errors in the frontend. First argument
# is the field that contains the error, second argument is the error itself.
Error = tuple[Optional[str], Exception]

# A notification to be displayed. First argument ist the notification type
# (warning, info, error, success, question). Second argument is the message.
# Third argument are format parameters to be spplied to the message (post i18n).
NotificationType = str
Notification = tuple[NotificationType, str, CdEDBObject]

# A set of roles a user may have.
Role = str

# A set of realms a persona belongs to.
Realm = str

# Admin views a user may activate/deactivate.
AdminView = str

CdEDBLog = tuple[int, tuple[CdEDBObject, ...]]

PathLike = Union[pathlib.Path, str]
Path = pathlib.Path

T = TypeVar("T")


class User:
    """Container for a persona."""

    def __init__(self, *, persona_id: Optional[int] = None,
                 droid_class: Optional[type["APIToken"]] = None,
                 droid_token_id: Optional[int] = None,
                 roles: Optional[set[Role]] = None, display_name: str = "",
                 given_names: str = "", family_name: str = "",
                 username: str = "", orga: Optional[Collection[int]] = None,
                 moderator: Optional[Collection[int]] = None,
                 presider: Optional[Collection[int]] = None) -> None:
        self.persona_id = persona_id
        self.droid_class = droid_class
        self.droid_token_id = droid_token_id
        if self.persona_id and (self.droid_class or self.droid_token_id):
            raise ValueError("Cannot be both droid and persona.")
        self.roles = roles or {"anonymous"}
        self.username = username
        self.display_name = display_name
        self.given_names = given_names
        self.family_name = family_name
        self.orga: set[int] = set(orga) if orga else set()
        self.moderator: set[int] = set(moderator) if moderator else set()
        self.presider: set[int] = set(presider) if presider else set()
        self.admin_views: set[AdminView] = set()

    @property
    def available_admin_views(self) -> set[AdminView]:
        return roles_to_admin_views(self.roles)

    def init_admin_views_from_cookie(self, enabled_views_cookie: str) -> None:
        enabled_views = enabled_views_cookie.split(',')
        self.admin_views = self.available_admin_views & set(enabled_views)

    def persona_name(self) -> str:
        return make_persona_name({
            'given_names': self.given_names,
            'display_name': self.display_name,
            'family_name': self.family_name,
        })


if TYPE_CHECKING:
    from cdedb.frontend.common import AmbienceDict


class RequestState(ConnectionContainer):
    """Container for request info. Besides this and db accesses the python
    code should be state-less. This data structure enables several
    convenient semi-magic behaviours (magic enough to be nice, but non-magic
    enough to not be non-nice).
    """
    default_lang = "en"
    log_lang = "de"
    mail_lang = "de"

    def __init__(self, sessionkey: Optional[str], apitoken: Optional[str], user: User,
                 request: werkzeug.Request, notifications: Collection[Notification],
                 mapadapter: werkzeug.routing.MapAdapter,
                 requestargs: Optional[Mapping[str, Any]],
                 errors: Collection[Error],
                 values: Optional[CdEDBMultiDict],
                 begin: Optional[datetime.datetime],
                 lang: str,
                 translations: Mapping[str, gettext.NullTranslations],
                 ) -> None:
        """
        :param mapadapter: URL generator (specific for this request)
        :param requestargs: verbatim copy of the arguments contained in the URL
        :param values: Parameter values extracted via :py:func:`REQUESTdata`
          and :py:func:`REQUESTdatadict` decorators, which allows automatically
          filling forms in.
        :param lang: language code for i18n, currently only 'de' and 'en' are
            valid.
        :param translations: A mapping of language (like the `lang` parameter) to
            gettext translation object.
        :param begin: time where we started to process the request
        """
        self.ambience: AmbienceDict = {}  # type: ignore[typeddict-item]  # pylint: disable=used-before-assignment
        self.sessionkey = sessionkey
        self.apitoken = apitoken
        self.user = user
        self.request = request
        self.notifications = list(notifications)
        self.urls = mapadapter
        self.requestargs = requestargs or {}
        self._errors = list(errors)
        if not isinstance(values, werkzeug.datastructures.MultiDict):
            values = werkzeug.datastructures.MultiDict(values)
        self.values = values or werkzeug.datastructures.MultiDict()
        self.lang = lang
        self.translations = translations
        self.begin = begin or now()
        # Toggle to disable logging
        self.is_quiet = False
        # Toggle to ignore validation warnings. The value is parsed directly inside
        # application.py
        self.ignore_warnings = False
        # Is true, if the application detected an invalid (or no) CSRF token
        self.csrf_alert = False
        # Used for validation enforcement, set to False if a validator
        # is executed and then to True with the corresponding methods
        # of this class
        self.validation_appraised: Optional[bool] = None

    @property
    def gettext(self) -> Callable[[str], str]:
        return self.translations[self.lang].gettext

    @property
    def ngettext(self) -> Callable[[str, str, int], str]:
        return self.translations[self.lang].ngettext

    @property
    def default_gettext(self) -> Callable[[str], str]:
        return self.translations[self.default_lang].gettext

    @property
    def default_ngettext(self) -> Callable[[str, str, int], str]:
        return self.translations[self.default_lang].ngettext

    @property
    def log_gettext(self) -> Callable[[str], str]:
        return self.translations[self.log_lang].gettext

    @property
    def log_ngettext(self) -> Callable[[str, str, int], str]:
        return self.translations[self.log_lang].ngettext

    @property
    def mail_gettext(self) -> Callable[[str], str]:
        return self.translations[self.mail_lang].gettext

    @property
    def mail_ngettext(self) -> Callable[[str, str, int], str]:
        return self.translations[self.mail_lang].ngettext

    def notify(self, ntype: NotificationType, message: str,
               params: Optional[CdEDBObject] = None) -> None:
        """Store a notification for later delivery to the user."""
        if ntype not in NOTIFICATION_TYPES:
            raise ValueError(n_("Invalid notification type %(t)s found."),
                             {'t': ntype})
        params = params or {}
        self.notifications.append((ntype, message, params))

    def notify_return_code(self, code: Union[DefaultReturnCode, bool], *,
                           success: str = n_("Change committed."),
                           info: str = n_("Change pending."),
                           error: str = n_("Change failed.")) -> None:
        """Small helper to issue a notification based on a return code.

        We allow some flexibility in what type of return code we accept. It
        may be a boolean (with the obvious meanings), an integer (specifying
        the number of changed entries, and negative numbers for entries with
        pending review).

        :param success: Affirmative message for positive return codes.
        :param info: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            self.notify("error", error)
        elif code is True or code > 0:
            self.notify("success", success)
        elif code < 0:
            self.notify("info", info)
        else:
            raise RuntimeError(n_("Impossible."))

    def notify_validation(self) -> None:
        """Puts a notification about validation complaints, if there are some.

        This takes care of the distinction between validation errors and
        warnings, but does not cause the validation tracking to register
        a successful check.
        """
        if errors := self.retrieve_validation_errors():
            if all(isinstance(kind, ValidationWarning) for param, kind in errors):
                self.notify("warning", n_("Input seems faulty. Please double-check if"
                                          " you really want to save it."))
            else:
                self.notify("error", n_("Failed validation."))

    def append_validation_error(self, error: Error) -> None:
        """Register a new error, if the same error is not already present.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.
        """
        self.validation_appraised = False
        for k, e in self._errors:
            if k == error[0]:
                if e.args == error[1].args:
                    break
        else:
            self._errors.append(error)

    def extend_validation_errors(self, errors: Iterable[Error]) -> None:
        """Register a new (maybe empty) set of errors.

        Errors are only added if the same error is not already present.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.
        """
        self.validation_appraised = False
        for e in errors:
            self.append_validation_error(e)

    def has_validation_errors(self) -> bool:
        """Check whether validation errors exists.

        This (or its companion function) must be called in the
        lifetime of a request. Otherwise the application will throw an
        error.
        """
        self.validation_appraised = True
        return bool(self._errors)

    def ignore_validation_errors(self) -> None:
        """Explicitly mark validation errors as irrelevant.

        This (or its companion function) must be called in the
        lifetime of a request. Otherwise the application will throw an
        error.
        """
        self.validation_appraised = True

    def retrieve_validation_errors(self) -> list[Error]:
        """Take a look at the queued validation errors.

        This does not cause the validation tracking to register a
        successful check.
        """
        return self._errors

    def replace_validation_errors(self, errors: Collection[Error]) -> None:
        """Replace validation errors by another collection of errors.

        This is used for post-processing of some forms related to the Query class.
        It does not cause the validation tracking to register a
        successful check.
        """
        self._errors = list(errors)

    def get_validation_errors_dict(self) -> dict[Optional[str], list[Exception]]:
        ret: dict[Optional[str], list[Exception]] = {}
        for key, value in self.retrieve_validation_errors():
            ret.setdefault(key, []).append(value)
        return ret


if TYPE_CHECKING:
    from cdedb.backend.common import AbstractBackend
else:
    AbstractBackend = None

B = TypeVar("B", bound=AbstractBackend)
F = TypeVar("F", bound=Callable[..., Any])


def make_proxy(backend: B, internal: bool = False) -> B:
    """Wrap a backend to only expose functions with an access decorator.

    If we used an actual RPC mechanism, this would do some additional
    lifting to accomodate this.

    We need to use a function so we can cast the return value.
    We also need to use an inner class so we can provide __getattr__.
    """

    def wrapit(fun: F) -> F:
        @functools.wraps(fun)
        def wrapper(rs: RequestState, *args: Any, **kwargs: Any) -> Any:
            try:
                if not internal:
                    # Expose database connection for the backends
                    # noinspection PyProtectedMember
                    rs.conn = rs._conn  # pylint: disable=protected-access
                return fun(rs, *args, **kwargs)
            finally:
                if not internal:
                    rs.conn = None  # type: ignore[assignment]
        return cast(F, wrapper)

    class Proxy:
        def __getattr__(self, name: str) -> Any:
            attr = getattr(backend, name)
            if any([
                not getattr(attr, "access", False),
                getattr(attr, "internal", False) and not internal,
                not callable(attr),
            ]):
                raise PrivilegeError(n_("Attribute %(name)s not public"),
                                     {"name": name})

            return wrapit(attr)

        @staticmethod
        def get_backend_class() -> type[B]:
            return backend.__class__

    return cast(B, Proxy())


def setup_logger(name: str, logfile_path: pathlib.Path,
                 log_level: int, syslog_level: Optional[int] = None,
                 console_log_level: Optional[int] = None) -> logging.Logger:
    """Configure the :py:mod:`logging` module.

    Since this works hierarchical, it should only be necessary to call this
    once and then every child logger is routed through this configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.debug(f"Logger {name} already initialized.")
        return logger
    logger.propagate = False
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        '[%(asctime)s,%(name)s,%(levelname)s] %(message)s')
    file_handler = logging.FileHandler(str(logfile_path), delay=True, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if syslog_level:
        syslog_handler = logging.handlers.SysLogHandler()
        syslog_handler.setLevel(syslog_level)
        syslog_handler.setFormatter(formatter)
        logger.addHandler(syslog_handler)
    if console_log_level:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def glue(*args: str) -> str:
    """Join overly long strings, adds boundary white space for convenience.

    It would be possible to use auto string concatenation as in ``("a
    string" "another string")`` instead, but there you have to be
    careful to add boundary white space yourself, so we once preferred this
    explicit function.
    """
    return " ".join(args)


def build_msg(msg1: str, msg2: Optional[str] = None) -> str:
    """Construct log message with appropriate punctuation"""
    if msg2:
        return msg1 + ": " + msg2
    else:
        return msg1 + "."


S = TypeVar("S")


def merge_dicts(targetdict: MutableMapping[T, S], *dicts: Mapping[T, S]) -> None:
    """Merge all dicts into the first one, but do not overwrite.

    This is basically the :py:meth:`dict.update` method, but existing
    keys take precedence.

    This is done inplace to allow the target dict to be a multi dict. If
    we create a new return dict we would have to add extra logic to
    cater for this.

    Additionally if the target is a MultiDict we use the correct method for
    setting list-type values.
    """
    if targetdict is None:
        raise ValueError(n_("No inputs given."))
    for adict in dicts:
        for key, value in adict.items():
            if key not in targetdict:
                if (isinstance(value, collections.abc.Collection)
                        and not isinstance(value, str)
                        and isinstance(targetdict, werkzeug.datastructures.MultiDict)):
                    if isinstance(value, dict) and "id" in value:
                        targetdict[key] = value["id"]
                    else:
                        targetdict.setlist(key, value)
                else:
                    targetdict[key] = value


BytesLike = Union[bytes, bytearray, memoryview]


def get_hash(*args: BytesLike) -> str:
    """Helper to calculate a hexadecimal hash of an arbitrary object.

    This uses SHA512. Use this function to assure the same hash is used
    everywhere.

    Note that this is not a replacement for the cryptographic hashing with
    salts used in assembly votes, but rather for identifying and
    differentiating files, like attachments and profile pictures.
    """
    hasher = hashlib.sha512()
    for obj in args:
        hasher.update(obj)
    return hasher.hexdigest()


def now() -> datetime.datetime:
    """Return an up to date timestamp.

    This is a separate function so we do not forget to make it time zone
    aware.
    """
    return datetime.datetime.now(datetime.timezone.utc)


_NEARLY_DELTA_DEFAULT = datetime.timedelta(minutes=10)


class NearlyNow(datetime.datetime):
    """This is something, that equals an automatically generated timestamp.

    Since automatically generated timestamp are not totally predictible,
    we use this to avoid nasty work arounds.
    """
    _delta: datetime.timedelta

    def __new__(cls, *args: Any, delta: datetime.timedelta = _NEARLY_DELTA_DEFAULT,
                **kwargs: Any) -> "NearlyNow":
        self = super().__new__(cls, *args, **kwargs)
        self._delta = delta
        return self

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, datetime.datetime):
            delta = other - self
            return self._delta > delta > -1 * self._delta
        return False

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    @classmethod
    def from_datetime(cls, datetime: datetime.datetime) -> "NearlyNow":
        ret = cls.fromisoformat(datetime.isoformat())
        return ret


def nearly_now(delta: datetime.timedelta = _NEARLY_DELTA_DEFAULT) -> NearlyNow:
    """Create a NearlyNow."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return NearlyNow(
        year=now.year, month=now.month, day=now.day, hour=now.hour,
        minute=now.minute, second=now.second, tzinfo=datetime.timezone.utc, delta=delta)


def make_persona_forename(persona: CdEDBObject,
                          only_given_names: bool = False,
                          only_display_name: bool = False,
                          given_and_display_names: bool = False) -> str:
    """Construct the forename of a persona according to the display name specification.

    The name specification can be found at the documentation page about
    "User Experience Conventions".
    """
    if only_display_name + only_given_names + given_and_display_names > 1:
        raise RuntimeError(n_("Invalid use of keyword parameters."))
    display_name: str = persona.get('display_name', "")
    given_names: str = persona['given_names']
    if only_given_names:
        return given_names
    elif only_display_name:
        return display_name
    elif given_and_display_names:
        if not display_name or display_name == given_names:
            return given_names
        else:
            return f"{given_names} ({display_name})"
    elif display_name and display_name in given_names:
        return display_name
    return given_names


def make_persona_name(persona: CdEDBObject,
                      only_given_names: bool = False,
                      only_display_name: bool = False,
                      given_and_display_names: bool = False,
                      with_family_name: bool = True,
                      with_titles: bool = False) -> str:
    """Format the name of a given persona according to the display name specification

    This is the Python pendant of the `util.persona_name()` macro.
    For a full specification, which name variant should be used in which context, see
    the documentation page about "User Experience Conventions".
    """
    forename = make_persona_forename(
        persona, only_given_names=only_given_names, only_display_name=only_display_name,
        given_and_display_names=given_and_display_names)
    ret = []
    if with_titles and persona.get('title'):
        ret.append(persona['title'])
    ret.append(forename)
    if with_family_name:
        ret.append(persona['family_name'])
    if with_titles and persona.get('name_supplement'):
        ret.append(persona['name_supplement'])
    return " ".join(ret)


def compute_checkdigit(value: int) -> str:
    """Map an integer to the checksum used for UI purposes.

    This checkdigit allows for error detection if somebody messes up a
    handwritten ID or such.

    Most of the time, the integer will be a persona id.
    """
    digits = []
    tmp = value
    while tmp > 0:
        digits.append(tmp % 10)
        tmp = tmp // 10
    dsum = sum((i + 2) * d for i, d in enumerate(digits))
    return "0123456789X"[-dsum % 11]


def lastschrift_reference(persona_id: int, lastschrift_id: int) -> str:
    """Return an identifier for usage with the bank.

    This is the so called 'Mandatsreferenz'.
    """
    return (
        f"CDE-I25-{persona_id}-{compute_checkdigit(persona_id)}"
        f"-{lastschrift_id}-{compute_checkdigit(lastschrift_id)}"
    )


def _small_int_to_words(num: int, lang: str) -> str:
    """Convert a small integer into a written representation.

    Helper for the general function.

    :param lang: Currently we only suppert 'de'.
    """
    if num < 0 or num > 999:
        raise ValueError(n_("Out of supported scope."))
    digits = tuple((num // 10 ** i) % 10 for i in range(3))
    if lang == "de":
        atoms = ("null", "ein", "zwei", "drei", "vier", "fünf", "sechs",
                 "sieben", "acht", "neun", "zehn", "elf", "zwölf", "dreizehn",
                 "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn",
                 "neunzehn")
        tens = ("", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig",
                "siebzig", "achtzig", "neunzig")
        ret = ""
        if digits[2]:
            ret += atoms[digits[2]] + "hundert"
        if num % 100 < 20:
            if num % 100:
                ret += atoms[num % 100]
            return ret
        if digits[0]:
            ret += atoms[digits[0]]
        if digits[0] and digits[1]:
            ret += "und"
        if digits[1]:
            ret += tens[digits[1]]
        return ret
    else:
        raise NotImplementedError(n_("Not supported."))


def int_to_words(num: int, lang: str) -> str:
    """Convert an integer into a written representation.

    This is for the usage such as '2 apples' -> 'two apples'.

    :param lang: Currently we only support 'de'.
    """
    if num < 0 or num > 999999:
        raise ValueError(n_("Out of supported scope."))
    if lang == "de":
        if num == 0:
            return "null"
        multipliers = ("", "tausend")
        number_words = []
        tmp = num
        while tmp > 0:
            number_words.append(_small_int_to_words(tmp % 1000, lang))
            tmp = tmp // 1000
        ret = ""
        for number_word, multiplier in reversed(tuple(zip(number_words,
                                                          multipliers))):
            if number_word != "null":
                ret += number_word + multiplier
        return ret
    else:
        raise NotImplementedError(n_("Not supported."))


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle the types that occur for us."""
    # pylint: disable=arguments-differ

    @overload
    def default(self, obj: Union[datetime.date, datetime.datetime,
                                 decimal.Decimal]) -> str: ...

    @overload
    def default(self, obj: set[T]) -> tuple[T, ...]: ...

    def default(self, obj: Any) -> Union[str, tuple[Any, ...], dict[str, Any]]:
        import cdedb.models.common as models  # pylint: disable=import-outside-toplevel
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return str(obj)
        elif isinstance(obj, set):
            return tuple(obj)
        elif isinstance(obj, models.CdEDataclass):
            return obj.as_dict()
        return super().default(obj)


def json_serialize(data: Any, **kwargs: Any) -> str:
    """Do beefed up JSON serialization."""
    return json.dumps(data, indent=4, cls=CustomJSONEncoder, **kwargs)


class PsycoJson(psycopg2.extras.Json):
    """Json encoder for consumption by psycopg.

    This is the official way of customizing the serialization process by
    subclassing the appropriate class.
    """

    def dumps(self, obj: Any) -> str:
        return json_serialize(obj)


def pairwise(iterable: Iterable[T]) -> Iterable[tuple[T, T]]:
    """Iterate over adjacent pairs of values of an iterable.

    For the input [1, 3, 6, 10] this returns [(1, 3), (3, 6), (6, 10)].
    """
    x, y = itertools.tee(iterable)
    next(y, None)
    return zip(x, y)


#: Magic value of shortname of the ballot candidate representing the bar.
ASSEMBLY_BAR_SHORTNAME = Candidate("_bar_")


@overload
def unwrap(data: None) -> None: ...


@overload
def unwrap(data: Mapping[Any, T]) -> T: ...


@overload
def unwrap(data: Collection[T]) -> T: ...


def unwrap(data: Union[None, Mapping[Any, T], Collection[T]]) -> Optional[T]:
    """Remove one nesting layer (of lists, etc.).

    This is here to replace code like ``foo = bar[0]`` where bar is a
    list with a single element. This offers some more amenities: it
    works on dicts and performs validation.

    In case of an error (e.g. wrong number of elements) this raises an
    error.

    Beware, that this behaves differently for mappings than other iterations,
    in that it uses the values instead of the keys. To unwrap the keys pass
    `data.keys()` instead.
    """
    if data is None:
        return None
    if isinstance(data, (str, bytes)):
        raise TypeError(n_("Cannot unwrap str or bytes. Got %(data)s."),
                        {'data': type(data)})
    if not isinstance(data, collections.abc.Collection):
        raise TypeError(
            n_("Can only unwrap collections. Got %(data)s."),
            {'data': type(data)})
    if not len(data) == 1:
        raise ValueError(
            n_("Can only unwrap collections with one element."
               " Got %(len)s elements."),
            {'len': len(data)})
    if isinstance(data, collections.abc.Mapping):
        [value] = data.values()
    elif isinstance(data, collections.abc.Collection):
        [value] = data
    else:
        raise NotImplementedError
    return value


@enum.unique
class LodgementsSortkeys(enum.Enum):
    """Sortkeys for lodgement overview."""
    #: default sortkey (currently equal to EntitySorter.lodgement)
    title = 1
    #: regular_capacity which is used in this part
    used_regular = 10
    #: camping_mat_capacity which is used in this part
    used_camping_mat = 11
    #: regular_capacity of this lodgement
    total_regular = 20
    #: camping_mat_capacity of this lodgement
    total_camping_mat = 21

    def is_used_sorting(self) -> bool:
        return self in (LodgementsSortkeys.used_regular,
                        LodgementsSortkeys.used_camping_mat)

    def is_total_sorting(self) -> bool:
        return self in (LodgementsSortkeys.total_regular,
                        LodgementsSortkeys.total_camping_mat)


@enum.unique
class AgeClasses(CdEIntEnum):
    """Abstraction for encapsulating properties like legal status changing with
    age.

    If there is any need for additional detail in differentiating this
    can be centrally added here.
    """
    full = 1  #: at least 18 years old
    u18 = 2  #: between 16 and 18 years old
    u16 = 3  #: between 14 and 16 years old
    u14 = 4  #: between 10 and 14 years old
    u10 = 5  #: under 10 years old, presumed child with parents

    def is_minor(self) -> bool:
        """Checks whether permission by a legal guardian is required.

        This excludes young children which are assumed to be accompanied.
        """
        return self in {AgeClasses.u14, AgeClasses.u16, AgeClasses.u18}

    def may_mix(self) -> bool:
        """Whether persons of this age may be legally accomodated in a mixed
        lodging together with the opposite gender.
        """
        return self in {AgeClasses.full, AgeClasses.u18, AgeClasses.u10}

    def with_guardian(self) -> bool:
        """Whether we assume that the child is accompanied by a legal guardian
        at the event, usually a parent."""
        return self == AgeClasses.u10


def deduct_years(date: datetime.date, years: int) -> datetime.date:
    """Convenience function to go back in time.

    Dates are nasty, in theory this should be a simple subtraction, but
    leap years create problems.
    """
    try:
        return date.replace(year=date.year - years)
    except ValueError:
        # this can happen in only one situation: we tried to move a leap
        # day into a year without leap
        assert (date.month == 2 and date.day == 29)
        return date.replace(year=date.year - years, day=28)


def determine_age_class(birth: datetime.date, reference: datetime.date,
                        ) -> AgeClasses:
    """Basically a constructor for :py:class:`AgeClasses`.

    :param reference: Time at which to check age status (e.g. the first day of
      a scheduled event).
    """
    if birth <= deduct_years(reference, 18):
        return AgeClasses.full
    if birth <= deduct_years(reference, 16):
        return AgeClasses.u18
    if birth <= deduct_years(reference, 14):
        return AgeClasses.u16
    if birth <= deduct_years(reference, 10):
        return AgeClasses.u14
    return AgeClasses.u10


@enum.unique
class LineResolutions(CdEIntEnum):
    """Possible actions during batch admission
    """
    create = 1  #: Create a new account with this data.
    skip = 2  #: Do nothing with this line.
    renew_trial = 3  #: Renew the trial membership of an existing account.
    update = 4  #: Update an existing account with this data.
    renew_and_update = 5  #: A combination of renew_trial and update.
    none = 10  #: No resolution was chosen.

    def do_trial(self) -> bool:
        """Whether to grant a trial membership."""
        return self in {LineResolutions.renew_trial,
                        LineResolutions.renew_and_update}

    def do_update(self) -> bool:
        """Whether to incorporate the new data (address, ...)."""
        return self in {LineResolutions.update,
                        LineResolutions.renew_and_update}

    def is_modification(self) -> bool:
        """Whether we modify an existing account.

        In this case we do not create a new account."""
        return self in {LineResolutions.renew_trial,
                        LineResolutions.update,
                        LineResolutions.renew_and_update}


@enum.unique
class GenesisDecision(CdEIntEnum):
    """Possible decisions during review of a genesis request."""
    approve = 1  #: Approve the request and create a new account.
    deny = 2  #: Deny the request. Do not create or update an account.
    #: Deny the request but update an existing account, dearchiving it if necessary.
    update = 3

    def is_create(self) -> bool:
        return self == GenesisDecision.approve

    def is_update(self) -> bool:
        return self == GenesisDecision.update


#: magic number which signals our makeshift algebraic data type
INFINITE_ENUM_MAGIC_NUMBER = 0


def infinite_enum(aclass: T) -> T:
    """Decorator to document infinite enums.

    This only sets a flag on the class for documentation and
    introspection purposes.

    Infinite enums are sadly not directly supported by python which
    means, that we have to emulate them on our own.

    We implement them by pairing the enum with an int and assigning a
    special enum value to the meaning "see the int value" (namely
    :py:const:`INFINITE_ENUM_MAGIC_NUMBER`).

    Furthermore by convention the int is always non-negative and the
    enum can have additional states which are all associated with
    negative values. In case of an additional enum state, the int is
    None.

    In the code they are stored as an :py:data:`InfiniteEnum`."""
    setattr(aclass, "infinite_enum", True)
    return aclass


E = TypeVar("E", bound=CdEIntEnum)


@functools.total_ordering
class InfiniteEnum(Generic[E]):
    """Storage facility for infinite enums with associated data

    Also see :py:func:`infinite_enum`"""

    # noinspection PyShadowingBuiltins
    def __init__(self, enum: E, int_: int):
        self.enum = enum
        self.int = int_

    @property
    def value(self) -> int:
        if self.enum == INFINITE_ENUM_MAGIC_NUMBER:
            return self.int
        return self.enum.value

    def __str__(self) -> str:
        if self.enum == INFINITE_ENUM_MAGIC_NUMBER:
            return f"{self.enum}({self.int})"
        return str(self.enum)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, InfiniteEnum):
            return self.value == other.value
        if isinstance(other, int):
            return self.value == other
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, InfiniteEnum):
            return self.value < other.value
        if isinstance(other, int):
            return self.value < other
        return NotImplemented


@infinite_enum
@enum.unique
class CourseFilterPositions(CdEIntEnum):
    """Selection possibilities for the course assignment tool.

    We want to find registrations which have a specific course as choice
    or something else. Where exactly we search for the course is
    specified via this enum.
    """
    #: This is the reference to the infinite enum int.
    specific_rank = INFINITE_ENUM_MAGIC_NUMBER
    instructor = -1  #: Being a course instructor for the course in question.
    any_choice = -5  #: Having chosen the course (in any choice)
    assigned = -6  #: Being in this course either as participant or instructor.
    anywhere = -7  #: Having chosen the course, being instructor or participant.


@infinite_enum
@enum.unique
class CourseChoiceToolActions(CdEIntEnum):
    """Selection possibilities for the course assignment tool.

    Specify the action to take.
    """
    #: reference to the infinite enum int
    specific_rank = INFINITE_ENUM_MAGIC_NUMBER
    assign_fixed = -4  #: the course is specified separately
    assign_auto = -5  #: somewhat intelligent algorithm


@enum.unique
class Accounts(enum.Enum):
    """Store the existing CdE Accounts."""
    Account0 = "DE26370205000008068900"
    Account1 = "DE96370205000008068901"
    Festgeld = "DE45370205000010042605"
    # Fallback if Account is none of the above
    Unknown = "Unknown"

    def display_str(self) -> str:
        return {
            Accounts.Account0: "8068900",
            Accounts.Account1: "8068901",
            Accounts.Festgeld: "Festgeld",
            Accounts.Unknown: "Unknown",
        }[self]


@enum.unique
class ConfidenceLevel(CdEIntEnum):
    """Store the different Levels of Confidence about the prediction."""
    Null = 0
    Low = 1
    Medium = 2
    High = 3
    Full = 4

    @classmethod
    def destroy(cls) -> "ConfidenceLevel":
        return cls.Null

    def decrease(self, amount: int = 1) -> "ConfidenceLevel":
        if self.value - amount > self.__class__.Null.value:
            return self.__class__(self.value - amount)
        else:
            return self.__class__.Null

    def increase(self, amount: int = 1) -> "ConfidenceLevel":
        if self.value + amount < self.__class__.Full.value:
            return self.__class__(self.value + amount)
        else:
            return self.__class__.Full

    def __format__(self, format_spec: str) -> str:
        return str(self)


@enum.unique
class TransactionType(CdEIntEnum):
    """Store the type of a Transactions."""
    MembershipFee = 1
    EventFee = 2
    Donation = 3
    LastschriftInitiative = 4
    Retoure = 5
    Other = 100

    EventFeeRefund = 10
    InstructorRefund = 11
    EventExpenses = 12
    Expenses = 13
    AccountFee = 14
    OtherPayment = 200

    Unknown = 1000

    @property
    def has_event(self) -> bool:
        return self in {TransactionType.EventFee,
                        TransactionType.EventFeeRefund,
                        TransactionType.InstructorRefund,
                        TransactionType.EventExpenses,
                        }

    @property
    def has_member(self) -> bool:
        return self in {TransactionType.MembershipFee,
                        TransactionType.EventFee,
                        TransactionType.LastschriftInitiative,
                        }

    @property
    def is_unknown(self) -> bool:
        return self in {TransactionType.Unknown,
                        TransactionType.Other,
                        TransactionType.OtherPayment,
                        }

    def old(self) -> str:
        """Return a string representation compatible with the old excel
        style.
        """
        if self == TransactionType.MembershipFee:
            return "Mitgliedsbeitrag"
        if self in {TransactionType.EventFee,
                    TransactionType.EventExpenses,
                    TransactionType.EventFeeRefund,
                    TransactionType.InstructorRefund}:
            return "Teilnahmebeitrag"
        if self == TransactionType.LastschriftInitiative:
            return "LastschriftInitiative"
        if self == TransactionType.Donation:
            return "Sonstiges"
        else:
            return "Sonstiges"

    def display_str(self) -> str:
        """
        Return a string representation for the TransactionType meant to be displayed.

        These are _not_ translated on purpose, so that the generated download
        is the same regardless of locale.
        """
        display_str = {
            TransactionType.MembershipFee: "Mitgliedsbeitrag",
            TransactionType.EventFee: "Teilnahmebeitrag",
            TransactionType.Donation: "Spende",
            TransactionType.LastschriftInitiative: "Lastschriftinitiative",
            TransactionType.Retoure: "Storno",
            TransactionType.Other: "Sonstiges",
            TransactionType.EventFeeRefund:
                "Teilnehmererstattung",
            TransactionType.InstructorRefund: "KL-Erstattung",
            TransactionType.EventExpenses:
                "Veranstaltungsausgabe",
            TransactionType.Expenses: "Ausgabe",
            TransactionType.AccountFee: "Kontogebühr",
            TransactionType.OtherPayment: "Andere Zahlung",
            TransactionType.Unknown: "Unbekannt",
        }
        return display_str.get(self, str(self))


UMLAUT_MAP = {
    "ä": "ae", "æ": "ae",
    "Ä": "AE", "Æ": "AE",
    "ö": "oe", "ø": "oe", "œ": "oe",
    "Ö": "Oe", "Ø": "Oe", "Œ": "Oe",
    "ü": "ue",
    "Ü": "Ue",
    "ß": "ss",
    "à": "a", "á": "a", "â": "a", "ã": "a", "å": "a", "ą": "a",
    "À": "A", "Á": "A", "Â": "A", "Ã": "A", "Å": "A", "Ą": "A",
    "ç": "c", "č": "c", "ć": "c",
    "Ç": "C", "Č": "C", "Ć": "C",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ę": "e",
    "È": "E", "É": "E", "Ê": "E", "Ë": "E", "Ę": "E",
    "ì": "i", "í": "i", "î": "i", "ï": "i",
    "Ì": "I", "Í": "I", "Î": "I", "Ï": "I",
    "ł": "l",
    "Ł": "L",
    "ñ": "n", "ń": "n",
    "Ñ": "N", "Ń": "N",
    "ò": "o", "ó": "o", "ô": "o", "õ": "o", "ő": "o",
    "Ò": "O", "Ó": "O", "Ô": "O", "Õ": "O", "Ő": "O",
    "ù": "u", "ú": "u", "û": "u", "ű": "u",
    "Ù": "U", "Ú": "U", "Û": "U", "Ű": "U",
    "ý": "y", "ÿ": "y",
    "Ý": "Y", "Ÿ": "Y",
    "ź": "z",
    "Ź": "Z",
}


def asciificator(s: str, *, normalize_whitespace: bool = False) -> str:
    """Pacify a string.

    Replace or omit all characters outside a known good set. This is to
    be used if your use case does not tolerate any fancy characters
    (like SEPA files).
    """
    ret = ""
    for char in s:
        if char in UMLAUT_MAP:
            ret += UMLAUT_MAP[char]
        elif char in (  # pylint: disable=superfluous-parens
            string.ascii_letters + string.digits + " /-?:().,+"
        ):
            ret += char
        else:
            ret += ' '
    if normalize_whitespace:
        ret = re.sub(r"\s+", " ", ret)
    return ret


# According to https://en.wikipedia.org/wiki/Filename#Reserved_characters_and_words
FILENAME_SANITIZE_MAP = str.maketrans({
    x: '_'
    for x in "/\\?%*:|\"<> ."
})


def sanitize_filename(name: str) -> str:
    """Sanitize filenames by replacing forbidden and problematic characters with '_'."""
    return name.translate(FILENAME_SANITIZE_MAP)


MaybeStr = TypeVar("MaybeStr", str, type[None])


def diacritic_patterns(s: str, two_way_replace: bool = False) -> str:
    """Replace letters with a pattern matching expressions.

    Thus ommitting diacritics in the query input is possible.

    This is intended for use with regular expressions.

    :param two_way_replace: If this is True, replace all letter with a
      potential diacritic (independent of the presence of the diacritic)
      with a pattern matching all diacritic variations. If this is False
      only replace in case of no diacritic present.

      This can be used to search for occurences of names stored
      in the db within input, that may not contain proper diacritics
      (e.g. it may be constrained to ASCII).
    """
    if s is None:
        raise ValueError(f"Cannot apply diacritic patterns to {s!r}.")
    # if fragile special chars are present do nothing
    special_chars = r'\*+?{}()[]|'  # .^$ are also special but do not interfere
    if any(char in s for char in special_chars):
        return s
    # some of the diacritics in use according to wikipedia
    umlaut_map = (
        ("ae", "(ae|ä|æ)"),
        ("oe", "(oe|ö|ø|œ)"),
        ("ue", "(ue|ü)"),
        ("ss", "(ss|ß)"),
        ("a", "[aàáâãäåą]"),
        ("c", "[cçčć]"),
        ("e", "[eèéêëę]"),
        ("i", "[iìíîï]"),
        ("l", "[lł]"),
        ("n", "[nñń]"),
        ("o", "[oòóôõöøő]"),
        ("u", "[uùúûüű]"),
        ("y", "[yýÿ]"),
        ("z", "[zźż]"),
    )
    if not two_way_replace:
        for normal, replacement in umlaut_map:
            s = re.sub(normal, replacement, s, flags=re.IGNORECASE)
    else:
        for _, regex in umlaut_map:
            s = re.sub(regex, regex, s, flags=re.IGNORECASE)
    return s


UMLAUT_TRANSLATE_TABLE = str.maketrans({
    char: f"({char}|{repl})" if len(repl) > 1 else f"[{char}{repl}]"
    for char, repl in UMLAUT_MAP.items()})


def inverse_diacritic_patterns(s: str) -> str:
    """
    Replace diacritic letters in a search pattern with a regex that
    matches either the diacritic letter or its ASCII representation.

    This function does kind of the opposite thing than
    :func:`diacritic_patterns`: Instead of enhancing a search expression such
    that also searches for similiar words with diacritics, it takes a word with
    diacritic characters and enhances it to a search expression that will find
    the word even when written without the diacritics.
    """
    return s.translate(UMLAUT_TRANSLATE_TABLE)


def abbreviation_mapper(data: Sequence[T]) -> dict[T, str]:
    """Assign an unique combination of ascii letters to each element."""
    num_letters = ((len(data) - 1) // 26) + 1
    return {item: "".join(shortname) for item, shortname in zip(
        data, itertools.product(string.ascii_uppercase, repeat=num_letters))}


_tdelta = datetime.timedelta


def encode_parameter(salt: str, target: str, name: str, param: str,
                     persona_id: Optional[int],
                     timeout: Optional[_tdelta] = _tdelta(seconds=60)) -> str:
    """Crypographically secure a parameter. This allows two things:

    * trust user submitted data (which we beforehand gave to the user in
      signed form and which he is echoing back at us); this is used for
      example to preserve notifications during redirecting a POST-request,
      and
    * verify the origin of the data (since only we have the key for
      signing), this is convenient since we are mostly state-less (except
      the SQL layer) and thus the user can obtain a small amount of state
      where necessary; this is for example used by the password reset path
      to generate a short-lived reset link to be sent via mail, without
      storing a challenge in the database.

    The threat model is an attacker obtaining an encoded parameter and using
    it in an unforseen way to gain an advantage (we assume, that the crypto
    part is secure).

    Our counter measures restrict the usage of each instance in the
    following ways:

    * by purpose: the `target` and `name` components specify a unique purpose
    * by time: the `timeout` component binds to a time window
    * by identity: the `persona_id` component binds to a specific account

    The latter two can be individually relaxed, but at least one of them is
    required for security.

    The message format is A--B--C, where

    * A is 128 chars sha512 checksum of 'W--X--Y--Z--B--C' where W == salt,
      X == str(persona_id), Y == target, Z == name
    * B is 24 chars timestamp of format '%Y-%m-%d %H:%M:%S%z' or 24 dots
      describing when the parameter expires (and the latter meaning never)
    * C is an arbitrary amount chars of payload

    :param salt: secret used for signing the parameter
    :param persona_id: The id of the persona utilizing the parameter, may be
      None in which case everybody (including anonymous requests) can do so.
    :param target: The endpoint the parameter is designated for. If this is
      omitted, there are nasty replay attacks. Is only used to ensure the
      parameter is not abused for another ``target``.
    :param name: name of parameter, same security implications as ``target``
    :param timeout: time until parameter expires, if this is None, the
      parameter never expires
    """
    if persona_id is None and timeout is None:
        raise ValueError(n_(
            "Security degradation: anonymous and non-expiring parameter"))
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    if timeout is None:
        timestamp = 24 * '.'
    else:
        ttl = now() + timeout
        timestamp = ttl.strftime("%Y-%m-%d %H:%M:%S%z")
    message = f"{timestamp}--{param}"
    tohash = f"{target}--{str(persona_id)}--{name}--{message}"
    h.update(tohash.encode("utf-8"))
    return f"{h.hexdigest()}--{message}"


def decode_parameter(salt: str, target: str, name: str, param: str,
                     persona_id: Optional[int],
                     ) -> Union[tuple[bool, None], tuple[None, str]]:
    """Inverse of :py:func:`encode_parameter`. See there for
    documentation.

    :returns: The string is the decoded message or ``None`` if any failure
      occured. The boolean is True if the failure was a timeout, False if
      the failure was something else and None if no failure occured.
    """
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    mac, message = param[0:128], param[130:]
    tohash = f"{target}--{str(persona_id)}--{name}--{message}"
    h.update(tohash.encode("utf-8"))
    if not hmac.compare_digest(h.hexdigest(), mac):
        if persona_id:
            # Allow non-anonymous requests for parameters with anonymous access
            return decode_parameter(salt, target, name, param, persona_id=None)
        _LOGGER.debug(f"Hash mismatch ({h.hexdigest()} != {mac}) for {tohash}")
        return False, None
    timestamp = message[:24]
    if timestamp == 24 * '.':
        pass
    else:
        ttl = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S%z")
        if ttl <= now():
            _LOGGER.debug(f"Expired protected parameter {tohash}")
            return True, None
    return None, message[26:]


def parse_date(val: str) -> datetime.date:
    """Make a string into a date.

    We only support a limited set of formats to avoid any surprises
    """
    formats = (("%Y-%m-%d", 10), ("%Y%m%d", 8), ("%d.%m.%Y", 10),
               ("%m/%d/%Y", 10), ("%d.%m.%y", 8))
    for fmt, _ in formats:
        try:
            return datetime.datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    # Shorten strings to allow datetimes as inputs
    for fmt, length in formats:
        try:
            return datetime.datetime.strptime(val[:length], fmt).date()
        except ValueError:
            pass
    raise ValueError(n_("Invalid date string."))


def parse_datetime(
    val: str, default_date: Optional[datetime.date] = None,
) -> datetime.date:
    """Make a string into a datetime.

    We only support a limited set of formats to avoid any surprises
    """
    date_formats = ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%d.%m.%y")
    connectors = ("T", " ")
    time_formats = (
        "%H:%M:%S.%f%z", "%H:%M:%S%z", "%H:%M:%S.%f", "%H:%M:%S", "%H:%M")
    formats = itertools.chain(
        map("".join, itertools.product(date_formats, connectors, time_formats)),
        map(" ".join, itertools.product(time_formats, date_formats)),
    )
    ret = None
    for fmt in formats:
        try:
            ret = datetime.datetime.strptime(val, fmt)
            break
        except ValueError:
            pass
    # TODO This code seems to be unsed.
    if ret is None and default_date:
        # Note the difference between formats and time_formats!
        for fmt in time_formats:
            try:
                ret = datetime.datetime.strptime(val, fmt)
                ret = ret.replace(
                    year=default_date.year, month=default_date.month,
                    day=default_date.day)
                break
            except ValueError:
                pass
    if ret is None:
        ret = datetime.datetime.fromisoformat(val)
    if ret.tzinfo is None:
        timezone: zoneinfo.ZoneInfo = _CONFIG["DEFAULT_TIMEZONE"]
        ret = ret.replace(tzinfo=timezone)
    return ret.astimezone(datetime.timezone.utc)


def parse_phone(val: str) -> str:
    # This kind of duplicates the phone validator, because our needs at error handling
    # are very different.
    phone: phonenumbers.PhoneNumber = phonenumbers.parse(val, region="DE")
    # handle the phone number as normalized string internally
    return phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)


def cast_fields(data: CdEDBObject, fields: "CdEDataclassMap[models_event.EventField]",
                ) -> CdEDBObject:
    """Helper to deserialize json fields.

    We serialize some classes as strings and need to undo this upon
    retrieval from the database.
    """
    spec: dict[str, const.FieldDatatypes]
    spec = {f.field_name: f.kind for f in fields.values()}
    casters: dict[const.FieldDatatypes, Callable[[Any], Any]] = {
        const.FieldDatatypes.int: lambda x: x,
        const.FieldDatatypes.str: lambda x: x,
        const.FieldDatatypes.float: lambda x: x,
        const.FieldDatatypes.date: parse_date,
        const.FieldDatatypes.datetime: parse_datetime,
        const.FieldDatatypes.bool: lambda x: x,
        const.FieldDatatypes.non_negative_int: lambda x: x,
        const.FieldDatatypes.non_negative_float: lambda x: x,
        # normalized string: id on read
        const.FieldDatatypes.phone: lambda x: x,
    }

    def _do_cast(key: str, val: Any) -> Any:
        if val is None:
            return None
        if key in spec:
            return casters[spec[key]](val)
        return val

    return {key: _do_cast(key, val) for key, val in data.items()}


#: Set of possible values for ``ntype`` in
#: :py:meth:`RequestState.notify`. Must conform to the regex
#: ``[a-z]+``.
NOTIFICATION_TYPES: set[NotificationType] = {"success", "info", "question",
                                             "warning", "error"}

#: The form field name used for the anti CSRF token.
#: It should be added to all data modifying form using the
#: util.anti_csrf_token template macro and is check by the application.
ANTI_CSRF_TOKEN_NAME = "_anti_csrf"
#: The value the anti CSRF token is expected to have
ANTI_CSRF_TOKEN_PAYLOAD = "_anti_csrf_check"

#: The form field name used to ignore ValidationWarnings.
#: This is added on-the-fly by util.form_input_submit if needed
IGNORE_WARNINGS_NAME = "_magic_ignore_warnings"

#: Version tag, so we know that we don't run out of sync with exported event
#: data. This has to be incremented whenever the event schema changes.
#: If changes to the partial export and import are backwards compatible,
#: the minor version may be incremented.
#: If you increment this, it must be incremented in make_offline_vm.py as well.
EVENT_SCHEMA_VERSION = (17, 2)

#: Default number of course choices of new event course tracks
DEFAULT_NUM_COURSE_CHOICES = 3

EPSILON = 10 ** (-6)  #:

#: Specification for the output date format of money transfers.
#: Note how this differs from the input in that we use 4 digit years.
PARSE_OUTPUT_DATEFORMAT = "%d.%m.%Y"
