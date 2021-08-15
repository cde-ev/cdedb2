#!/usr/bin/env python3

"""Global utility functions."""

import collections
import collections.abc
import datetime
import decimal
import enum
import functools
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
from typing import (
    Generic, TYPE_CHECKING, Any, Callable, Collection, Container, Dict, Generator,
    Iterable, KeysView, List, Mapping, MutableMapping, Optional, Set, Tuple, Type,
    TypeVar, Union, cast, overload
)

import icu
import psycopg2.extras
import pytz
import werkzeug
import werkzeug.exceptions
import werkzeug.routing

import cdedb.database.constants as const
from cdedb.database.connection import IrradiatedConnection

_LOGGER = logging.getLogger(__name__)

# Global unified collator to be used when sorting.
# The locale provided here must exist as collation in SQL for this to
# work properly.
# 'de_DE.UTF-8@colNumeric=yes' is an equivalent choice for LOCAL, but is less
# compatible to use as a collation name in postgresql.
LOCALE = 'de-u-kn-true'
COLLATOR = icu.Collator.createInstance(icu.Locale(LOCALE))

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = Dict[str, Any]
if TYPE_CHECKING:
    CdEDBMultiDict = werkzeug.datastructures.MultiDict[str, Any]
else:
    CdEDBMultiDict = werkzeug.datastructures.MultiDict

# Map of pseudo objects, indexed by their id, as returned by
# `get_events`, event["parts"], etc.

CdEDBObjectMap = Dict[int, CdEDBObject]

# Same as above, but we also allow negative ints (for creation, not reflected
# in the type] and None (for deletion). Used in `_set_tracks` and partial
# import diff.
CdEDBOptionalMap = Dict[int, Optional[CdEDBObject]]

# An integer with special semantics. Positive return values indicate success,
# a return of zero signals an error, a negative return value indicates some
# special case like a change pending review.
DefaultReturnCode = int

# Return value for `delete_foo_blockers` part of the deletion interface.
# The key specifies the kind of blocker, the value is a list of blocking ids.
# For some blockers the value might have a different type, mostly when that
# blocker blocks deletion without the option to cascadingly delete.
DeletionBlockers = Dict[str, List[int]]

# Pseudo error objects used to display errors in the frontend. First argument
# is the field that contains the error, second argument is the error itself.
Error = Tuple[Optional[str], Exception]

# A notification to be displayed. First argument ist the notification type
# (warning, info, error, success, question). Second argument is the message.
# Third argument are format parameters to be spplied to the message (post i18n).
NotificationType = str
Notification = Tuple[NotificationType, str, CdEDBObject]

# A set of roles a user may have.
Role = str

# A set of realms a persona belongs to.
Realm = str

# Admin views a user may activate/deactivate.
AdminView = str

CdEDBLog = Tuple[int, Tuple[CdEDBObject, ...]]

PathLike = Union[pathlib.Path, str]
Path = pathlib.Path

T = TypeVar("T")


class User:
    """Container for a persona."""

    def __init__(self, persona_id: Optional[int] = None,
                 roles: Set[Role] = None, display_name: str = "",
                 given_names: str = "", family_name: str = "",
                 username: str = "", orga: Collection[int] = None,
                 moderator: Collection[int] = None,
                 presider: Collection[int] = None) -> None:
        self.persona_id = persona_id
        self.roles = roles or {"anonymous"}
        self.username = username
        self.display_name = display_name
        self.given_names = given_names
        self.family_name = family_name
        self.orga: Set[int] = set(orga) if orga else set()
        self.moderator: Set[int] = set(moderator) if moderator else set()
        self.presider: Set[int] = set(presider) if presider else set()
        self.admin_views: Set[AdminView] = set()

    @property
    def available_admin_views(self) -> Set[AdminView]:
        return roles_to_admin_views(self.roles)

    def init_admin_views_from_cookie(self, enabled_views_cookie: str) -> None:
        enabled_views = enabled_views_cookie.split(',')
        self.admin_views = self.available_admin_views & set(enabled_views)


class RequestState:
    """Container for request info. Besides this and db accesses the python
    code should be state-less. This data structure enables several
    convenient semi-magic behaviours (magic enough to be nice, but non-magic
    enough to not be non-nice).
    """

    def __init__(self, sessionkey: Optional[str], apitoken: Optional[str],
                 user: User, request: werkzeug.Request,
                 notifications: Collection[Notification],
                 mapadapter: werkzeug.routing.MapAdapter,
                 requestargs: Optional[Dict[str, int]],
                 errors: Collection[Error],
                 values: Optional[CdEDBMultiDict], lang: str,
                 gettext: Callable[[str], str],
                 ngettext: Callable[[str, str, int], str],
                 coders: Optional[Mapping[str, Callable]],  # type: ignore
                 begin: Optional[datetime.datetime],
                 default_gettext: Callable[[str], str] = None,
                 default_ngettext: Callable[[str, str, int], str] = None):
        """
        :param mapadapter: URL generator (specific for this request)
        :param requestargs: verbatim copy of the arguments contained in the URL
        :param values: Parameter values extracted via :py:func:`REQUESTdata`
          and :py:func:`REQUESTdatadict` decorators, which allows automatically
          filling forms in.
        :param lang: language code for i18n, currently only 'de' and 'en' are
            valid.
        :param coders: Functions for encoding and decoding parameters primed
          with secrets. This is hacky, but sadly necessary.
        :param begin: time where we started to process the request
        :param default_gettext: default translation function used to ensure
            stability across different locales
        :param default_ngettext: default translation function used to ensure
            stability across different locales
        """
        self.ambience: Dict[str, CdEDBObject] = {}
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
        self.gettext = gettext
        self.ngettext = ngettext
        self.default_gettext = default_gettext or gettext
        self.default_ngettext = default_ngettext or ngettext
        self._coders = coders or {}
        self.begin = begin or now()
        # Visible version of the database connection
        # noinspection PyTypeChecker
        self.conn: IrradiatedConnection = None  # type: ignore
        # Private version of the database connection, only visible in the
        # backends (mediated by the make_proxy)
        # noinspection PyTypeChecker
        self._conn: IrradiatedConnection = None  # type: ignore
        # Toggle to disable logging
        self.is_quiet = False
        # Is true, if the application detected an invalid (or no) CSRF token
        self.csrf_alert = False
        # Used for validation enforcement, set to False if a validator
        # is executed and then to True with the corresponding methods
        # of this class
        self.validation_appraised: Optional[bool] = None

    def notify(self, ntype: NotificationType, message: str,
               params: CdEDBObject = None) -> None:
        """Store a notification for later delivery to the user."""
        if ntype not in NOTIFICATION_TYPES:
            raise ValueError(n_("Invalid notification type %(t)s found."),
                             {'t': ntype})
        params = params or {}
        self.notifications.append((ntype, message, params))

    def append_validation_error(self, error: Error) -> None:
        """Register a new  error.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.

        However in general the method extend_validation_errors()
        should be preferred since it activates the validation tracking
        even if no errors are present.
        """
        self.validation_appraised = False
        self._errors.append(error)

    def add_validation_error(self, error: Error) -> None:
        """Register a new error, if the same error is not already present."""
        for k, e in self._errors:
            if k == error[0]:
                if e.args == error[1].args:
                    break
        else:
            self.append_validation_error(error)

    def extend_validation_errors(self, errors: Iterable[Error]) -> None:
        """Register a new (maybe empty) set of errors.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.
        """
        self.validation_appraised = False
        self._errors.extend(errors)

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

    def retrieve_validation_errors(self) -> List[Error]:
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
                    rs.conn = rs._conn
                return fun(rs, *args, **kwargs)
            finally:
                if not internal:
                    rs.conn = None  # type: ignore
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
        def _get_backend_class() -> Type[B]:
            return backend.__class__

    return cast(B, Proxy())


def make_root_logger(name: str, logfile_path: PathLike,
                     log_level: int, syslog_level: int = None,
                     console_log_level: int = None) -> logging.Logger:
    """Configure the :py:mod:`logging` module.

    Since this works hierarchical, it should only be necessary to call this
     once and then every child logger is routed through this configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.debug("Logger {} already initialized.".format(name))
        return logger
    logger.propagate = False
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        '[%(asctime)s,%(name)s,%(levelname)s] %(message)s')
    file_handler = logging.FileHandler(str(logfile_path))
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
    logger.debug("Configured logger {}.".format(name))
    return logger


def glue(*args: str) -> str:
    """Join overly long strings, adds boundary white space for convenience.

    It would be possible to use auto string concatenation as in ``("a
    string" "another string")`` instead, but there you have to be
    careful to add boundary white space yourself, so we prefer this
    explicit function.
    """
    return " ".join(args)


S = TypeVar("S")


def merge_dicts(targetdict: Union[MutableMapping[T, S], CdEDBMultiDict],
                *dicts: Mapping[T, S]) -> None:
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
        for key in adict:
            if key not in targetdict:
                if (isinstance(adict[key], collections.abc.Sequence)
                        and not isinstance(adict[key], str)
                        and isinstance(targetdict, werkzeug.datastructures.MultiDict)):
                    targetdict.setlist(key, adict[key])
                else:
                    targetdict[key] = adict[key]


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
    return datetime.datetime.now(pytz.utc)


_NEARLY_DELTA_DEFAULT = datetime.timedelta(minutes=10)


class NearlyNow(datetime.datetime):
    """This is something, that equals an automatically generated timestamp.

    Since automatically generated timestamp are not totally predictible,
    we use this to avoid nasty work arounds.
    """
    _delta: datetime.timedelta

    def __new__(cls, *args: Any, delta: datetime.timedelta = _NEARLY_DELTA_DEFAULT,  # pylint: disable=arguments-differ
                **kwargs: Any) -> "NearlyNow":
        self = super().__new__(cls, *args, **kwargs)
        self._delta = delta
        return self

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, datetime.datetime):
            delta = self - other
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
    now = datetime.datetime.now(pytz.utc)
    return NearlyNow(
        year=now.year, month=now.month, day=now.day, hour=now.hour,
        minute=now.minute, second=now.second, tzinfo=pytz.utc, delta=delta)


class QuotaException(werkzeug.exceptions.TooManyRequests):
    """
    Exception for signalling a quota excess. This is thrown in
    :py:mod:`cdedb.backend.cde` and caught in
    :py:mod:`cdedb.frontend.application`. We use a custom class so that
    we can distinguish it from other exceptions.
    """


class PrivilegeError(RuntimeError):
    """
    Exception for signalling missing privileges. This Exception is thrown by the
    backend to indicate an unprivileged call to a backend function. However,
    this situation should be prevented by privilege checks in the frontend.
    Thus, we typically consider this Exception as an unexpected programming
    error. In some cases the frontend may catch and handle the exception
    instead of preventing it in the first place.
    """


class ArchiveError(RuntimeError):
    """
    Exception for signalling an exact error when archiving a persona
    goes awry.
    """


class PartialImportError(RuntimeError):
    """Exception for signalling a checksum mismatch in the partial import.

    Making this an exception rolls back the database transaction.
    """


class ValidationWarning(Exception):
    """Exception which should be suppressable by the user."""


def xsorted(iterable: Iterable[T], *, key: Callable[[Any], Any] = lambda x: x,
            reverse: bool = False) -> List[T]:
    """Wrapper for sorted() to achieve a natural sort.

    This replaces all strings in possibly nested objects with a sortkey
    matching an collation from the Unicode Collation Algorithm, provided
    by the icu library.

    In particular, this makes sure strings containing diacritics are
    sorted correctly, e.g. with ß = ss, a = ä, s = S etc. Furthermore, numbers
    (ints and decimals) are sorted correctly, even in midst of strings.
    However, negative numbers in strings are sorted by absolute value, before
    positive numbers, as minus and hyphens can not be distinguished.

    For users, the interface of this function should be identical
    to sorted().
    """

    def collate(sortkey: Any) -> Any:
        if isinstance(sortkey, str):
            return COLLATOR.getSortKey(sortkey)
        if isinstance(sortkey, collections.abc.Iterable):
            # Make sure strings in nested Iterables are sorted
            # correctly as well.
            return tuple(map(collate, sortkey))
        return sortkey

    return sorted(iterable, key=lambda x: collate(key(x)),  # pylint: disable=bad-builtin
                  reverse=reverse)


Sortkey = Tuple[Union[str, int, datetime.datetime], ...]
KeyFunction = Callable[[CdEDBObject], Sortkey]


# noinspection PyRedundantParentheses
class EntitySorter:
    """Provide a singular point for common sortkeys.

    This class does not need to be instantiated. It's method can be passed to
    `sorted` or `keydictsort_filter`.
    """

    @staticmethod
    def given_names(persona: CdEDBObject) -> Sortkey:
        return (persona['given_names'].lower(),)

    @staticmethod
    def family_name(persona: CdEDBObject) -> Sortkey:
        return (persona['family_name'].lower(),)

    @staticmethod
    def given_names_first(persona: CdEDBObject) -> Sortkey:
        return (persona['given_names'].lower(),
                persona['family_name'].lower(),
                persona['id'])

    @staticmethod
    def family_name_first(persona: CdEDBObject) -> Sortkey:
        return (persona['family_name'].lower(),
                persona['given_names'].lower(),
                persona['id'])

    # TODO decide whether we sort by first or last name
    persona = family_name_first

    @staticmethod
    def email(persona: CdEDBObject) -> Sortkey:
        return (str(persona['username']),)

    @staticmethod
    def address(persona: CdEDBObject) -> Sortkey:
        # TODO sort by translated country instead of country code?
        country = persona.get('country', "") or ""
        postal_code = persona.get('postal_code', "") or ""
        location = persona.get('location', "") or ""
        address = persona.get('address', "") or ""
        return (country, postal_code, location, address)

    @staticmethod
    def event(event: CdEDBObject) -> Sortkey:
        return (event['begin'], event['end'], event['title'], event['id'])

    @staticmethod
    def course(course: CdEDBObject) -> Sortkey:
        return (course['nr'], course['shortname'], course['id'])

    @staticmethod
    def lodgement(lodgement: CdEDBObject) -> Sortkey:
        return (lodgement['title'], lodgement['id'])

    @staticmethod
    def lodgement_group(lodgement_group: CdEDBObject) -> Sortkey:
        return (lodgement_group['title'], lodgement_group['id'])

    @staticmethod
    def event_part(event_part: CdEDBObject) -> Sortkey:
        return (event_part['part_begin'], event_part['part_end'],
                event_part['shortname'], event_part['id'])

    @staticmethod
    def course_track(course_track: CdEDBObject) -> Sortkey:
        return (course_track['sortkey'], course_track['id'])

    @staticmethod
    def event_field(event_field: CdEDBObject) -> Sortkey:
        return (event_field['field_name'], event_field['id'])

    @staticmethod
    def candidates(candidates: CdEDBObject) -> Sortkey:
        return (candidates['shortname'], candidates['id'])

    @staticmethod
    def assembly(assembly: CdEDBObject) -> Sortkey:
        return (assembly['signup_end'], assembly['id'])

    @staticmethod
    def ballot(ballot: CdEDBObject) -> Sortkey:
        return (ballot['title'], ballot['id'])

    @staticmethod
    def get_attachment_sorter(histories: CdEDBObject) -> KeyFunction:
        def attachment(attachment: CdEDBObject) -> Sortkey:
            attachment = histories[attachment['id']][attachment['current_version']]
            return (attachment['title'], attachment['attachment_id'])

        return attachment

    @staticmethod
    def attachment_version(version: CdEDBObject) -> Sortkey:
        return (version['attachment_id'], version['version'])

    @staticmethod
    def past_event(past_event: CdEDBObject) -> Sortkey:
        return (past_event['tempus'], past_event['id'])

    @staticmethod
    def past_course(past_course: CdEDBObject) -> Sortkey:
        return (past_course['nr'], past_course['title'], past_course['id'])

    @staticmethod
    def institution(institution: CdEDBObject) -> Sortkey:
        return (institution['shortname'], institution['id'])

    @staticmethod
    def transaction(transaction: CdEDBObject) -> Sortkey:
        return (transaction['issued_at'], transaction['id'])

    @staticmethod
    def genesis_case(genesis_case: CdEDBObject) -> Sortkey:
        return (genesis_case['ctime'], genesis_case['id'])

    @staticmethod
    def changelog(changelog_entry: CdEDBObject) -> Sortkey:
        return (changelog_entry['ctime'], changelog_entry['id'])

    @staticmethod
    def mailinglist(mailinglist: CdEDBObject) -> Sortkey:
        return (mailinglist['title'], mailinglist['id'])


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
    return "CDE-I25-{}-{}-{}-{}".format(
        persona_id, compute_checkdigit(persona_id), lastschrift_id,
        compute_checkdigit(lastschrift_id))


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
    # pylint: disable=method-hidden,arguments-differ

    @overload
    def default(self, obj: Union[datetime.date, datetime.datetime,
                                 decimal.Decimal]) -> str: ...

    @overload
    def default(self, obj: Set[T]) -> Tuple[T, ...]: ...

    def default(self, obj: Any) -> Union[str, Tuple[Any, ...]]:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return str(obj)
        elif isinstance(obj, set):
            return tuple(obj)
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


def pairwise(iterable: Iterable[T]) -> Iterable[Tuple[T, T]]:
    """Iterate over adjacent pairs of values of an iterable.

    For the input [1, 3, 6, 10] this returns [(1, 3), (3, 6), (6, 10)].
    """
    x, y = itertools.tee(iterable)
    next(y, None)
    return zip(x, y)


def _schulze_winners(d: Mapping[Tuple[str, str], int],
                     candidates: Collection[str]) -> List[str]:
    """This is the abstract part of the Schulze method doing the actual work.

    The candidates are the vertices of a graph and the metric (in form
    of ``d``) describes the strength of the links between the
    candidates, that is edge weights.

    We determine the strongest path from each vertex to each other
    vertex. This gives a transitive relation, which enables us thus to
    determine winners as maximal elements.
    """
    # First determine the strongst paths
    p = {(x, y): d[(x, y)] for x in candidates for y in candidates}
    for i in candidates:
        for j in candidates:
            if i == j:
                continue
            for k in candidates:
                if k in {i, j}:
                    continue
                p[(j, k)] = max(p[(j, k)], min(p[(j, i)], p[(i, k)]))
    # Second determine winners
    winners = []
    for i in candidates:
        if all(p[(i, j)] >= p[(j, i)] for j in candidates):
            winners.append(i)
    return winners


def schulze_evaluate(votes: Collection[str], candidates: Collection[str]
                     ) -> Tuple[str, List[Dict[str, Union[int, List[str]]]]]:
    """Use the Schulze method to cummulate preference list into one list.

    This is used by the assembly realm to tally votes -- however this is
    pretty abstract, so we move it here.

    Votes have the form ``3>0>1=2>4`` where the shortnames between the
    relation signs are exactly those passed in the ``candidates`` parameter.

    The Schulze method is described in the pdf found in the ``related``
    folder. Also the Wikipedia article is pretty nice.

    One thing to mention is, that we do not do any tie breaking. Since
    we allow equality in the votes, it seems reasonable to allow
    equality in the result too.

    For a nice set of examples see the test suite.

    :param candidates: We require that the candidates be explicitly
        passed. This allows for more flexibility (like returning a useful
        result for zero votes).
    :returns: The first Element is the aggregated result,
        the second is an more extended list, containing every level
        (descending) as dict with some extended information.
    """
    split_votes = tuple(
        tuple(lvl.split('=') for lvl in vote.split('>')) for vote in votes)

    def _subindex(alist: Collection[Container[str]], element: str) -> int:
        """The element is in the list at which position in the big list.

        :returns: ``ret`` such that ``element in alist[ret]``
        """
        for index, sublist in enumerate(alist):
            if element in sublist:
                return index
        raise ValueError(n_("Not in list."))

    # First we count the number of votes prefering x to y
    counts = {(x, y): 0 for x in candidates for y in candidates}
    for vote in split_votes:
        for x in candidates:
            for y in candidates:
                if _subindex(vote, x) < _subindex(vote, y):
                    counts[(x, y)] += 1

    # Second we calculate a numeric link strength abstracting the problem
    # into the realm of graphs with one vertex per candidate
    def _strength(support: int, opposition: int, totalvotes: int) -> int:
        """One thing not specified by the Schulze method is how to asses the
        strength of a link and indeed there are several possibilities. We
        use the strategy called 'winning votes' as advised by the paper of
        Markus Schulze.

        If two two links have more support than opposition, then the link
        with more supporters is stronger, if supporters tie then less
        opposition is used as secondary criterion.

        Another strategy which seems to have a more intuitive appeal is
        called 'margin' and sets the difference between support and
        opposition as strength of a link. However the discrepancy
        between the strategies is rather small, to wit all cases in the
        test suite give the same result for both of them. Moreover if
        the votes contain no ties both strategies (and several more) are
        totally equivalent.
        """
        # the margin strategy would be given by the following line
        # return support - opposition
        if support > opposition:
            return totalvotes * support - opposition
        elif support == opposition:
            return 0
        else:
            return -1

    d = {(x, y): _strength(counts[(x, y)], counts[(y, x)], len(votes))
         for x in candidates for y in candidates}
    # Third we execute the Schulze method by iteratively determining
    # winners
    result: List[List[str]] = []
    while True:
        done = {x for level in result for x in level}
        # avoid sets to preserve ordering
        remaining = tuple(c for c in candidates if c not in done)
        if not remaining:
            break
        winners = _schulze_winners(d, remaining)
        result.append(winners)

    # Return the aggregated preference list in the same format as the input
    # votes are.
    condensed = ">".join("=".join(level) for level in result)
    detailed = []
    for lead, follow in zip(result, result[1:]):
        level: Dict[str, Union[List[str], int]] = {
            'winner': lead,
            'loser': follow,
            'pro_votes': counts[(lead[0], follow[0])],
            'contra_votes': counts[(follow[0], lead[0])]
        }
        detailed.append(level)

    return condensed, detailed


#: Magic value of shortname of the ballot candidate representing the bar.
ASSEMBLY_BAR_SHORTNAME = "_bar_"


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
class AgeClasses(enum.IntEnum):
    """Abstraction for encapsulating properties like legal status changing with
    age.

    If there is any need for additional detail in differentiating this
    can be centrally added here.
    """
    full = 1  #: at least 18 years old
    u18 = 2  #: between 16 and 18 years old
    u16 = 3  #: between 14 and 16 years old
    u14 = 4  #: less than 14 years old

    def is_minor(self) -> bool:
        """Checks whether a legal guardian is required."""
        return self in {AgeClasses.u14, AgeClasses.u16, AgeClasses.u18}

    def may_mix(self) -> bool:
        """Whether persons of this age may be legally accomodated in a mixed
        lodging together with the opposite gender.
        """
        return self in {AgeClasses.full, AgeClasses.u18}


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


def determine_age_class(birth: datetime.date, reference: datetime.date
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
    return AgeClasses.u14


@enum.unique
class LineResolutions(enum.IntEnum):
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


#: magic number which signals our makeshift algebraic data type
INFINITE_ENUM_MAGIC_NUMBER = 0


def infinite_enum(aclass: T) -> T:
    """Decorator to document infinite enums.

    This does nothing and is only for documentation purposes.

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
    return aclass


E = TypeVar("E", bound=enum.IntEnum)


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
            return "{}({})".format(self.enum, self.int)
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
class CourseFilterPositions(enum.IntEnum):
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
class CourseChoiceToolActions(enum.IntEnum):
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
    Account0 = 8068900
    Account1 = 8068901
    Account2 = 8068902
    # Fallback if Account is none of the above
    Unknown = 0

    def __str__(self) -> str:
        return str(self.value)


@enum.unique
class TransactionType(enum.IntEnum):
    """Store the type of a Transactions."""
    MembershipFee = 1
    EventFee = 2
    Donation = 3
    I25p = 4
    Other = 5

    EventFeeRefund = 10
    InstructorRefund = 11
    EventExpenses = 12
    Expenses = 13
    AccountFee = 14
    OtherPayment = 15

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
                        TransactionType.I25p,
                        }

    @property
    def is_unknown(self) -> bool:
        return self in {TransactionType.Unknown,
                        TransactionType.Other,
                        TransactionType.OtherPayment
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
            return "Teilnehmerbeitrag"
        if self == TransactionType.I25p:
            return "Initiative 25+"
        if self == TransactionType.Donation:
            return "Spende"
        else:
            return "Sonstiges"

    def __str__(self) -> str:
        """
        Return a string represantation for the TransactionType.

        These are _not_ translated on purpose, so that the generated download
        is the same regardless of locale.
        """
        to_string = {TransactionType.MembershipFee.name: "Mitgliedsbeitrag",
                     TransactionType.EventFee.name: "Teilnehmerbeitrag",
                     TransactionType.Donation.name: "Spende",
                     TransactionType.I25p.name: "Initiative25+",
                     TransactionType.Other.name: "Sonstiges",
                     TransactionType.EventFeeRefund.name:
                         "Teilnehmererstattung",
                     TransactionType.InstructorRefund.name: "KL-Erstattung",
                     TransactionType.EventExpenses.name:
                         "Veranstaltungsausgabe",
                     TransactionType.Expenses.name: "Ausgabe",
                     TransactionType.AccountFee.name: "Kontogebühr",
                     TransactionType.OtherPayment.name: "Andere Zahlung",
                     TransactionType.Unknown.name: "Unbekannt",
                     }
        if self.name in to_string:
            return to_string[self.name]
        else:
            return repr(self)


class SemesterSteps(enum.Enum):
    billing = 1
    archival_notification = 2
    ejection = 10
    automated_archival = 11
    balance = 20
    advance = 30
    error = 100

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.name == other  # pylint: disable=comparison-with-callable
        return super().__eq__(other)


def mixed_existence_sorter(iterable: Union[Collection[int], KeysView[int]]
                           ) -> Generator[int, None, None]:
    """Iterate over a set of indices in the relevant way.

    That is first over the non-negative indices in ascending order and
    then over the negative indices in descending order.

    This is the desired order if the UI offers the possibility to
    create multiple new entities enumerated by negative IDs.
    """
    for i in xsorted(iterable):
        if i >= 0:
            yield i
    for i in reversed(xsorted(iterable)):
        if i < 0:
            yield i


def n_(x: str) -> str:
    """
    Alias of the identity for i18n.
    Identity function that shadows the gettext alias to trick pybabel into
    adding string to the translated strings.
    """
    return x


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


def asciificator(s: str) -> str:
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
    return ret


MaybeStr = TypeVar("MaybeStr", str, Type[None])


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
    ret = ""
    for char in s:
        if char in UMLAUT_MAP:
            repl = UMLAUT_MAP[char]
            ret += f"({char}|{repl})" if len(repl) > 1 else f"[{char}{repl}]"
        else:
            ret += char
    return ret


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
      omitted, there are nasty replay attacks.
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
    message = "{}--{}".format(timestamp, param)
    tohash = "{}--{}--{}--{}".format(target, str(persona_id), name, message)
    h.update(tohash.encode("utf-8"))
    return "{}--{}".format(h.hexdigest(), message)


def decode_parameter(salt: str, target: str, name: str, param: str,
                     persona_id: Optional[int]
                     ) -> Union[Tuple[bool, None], Tuple[None, str]]:
    """Inverse of :py:func:`encode_parameter`. See there for
    documentation.

    :returns: The string is the decoded message or ``None`` if any failure
      occured. The boolean is True if the failure was a timeout, False if
      the failure was something else and None if no failure occured.
    """
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    mac, message = param[0:128], param[130:]
    tohash = "{}--{}--{}--{}".format(target, str(persona_id), name, message)
    h.update(tohash.encode("utf-8"))
    if not hmac.compare_digest(h.hexdigest(), mac):
        if persona_id:
            # Allow non-anonymous requests for parameters with anonymous access
            return decode_parameter(salt, target, name, param, persona_id=None)
        _LOGGER.debug("Hash mismatch ({} != {}) for {}".format(
            h.hexdigest(), mac, tohash))
        return False, None
    timestamp = message[:24]
    if timestamp == 24 * '.':
        pass
    else:
        ttl = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S%z")
        if ttl <= now():
            _LOGGER.debug("Expired protected parameter {}".format(tohash))
            return True, None
    return None, message[26:]


def extract_roles(session: CdEDBObject, introspection_only: bool = False
                  ) -> Set[Role]:
    """Associate some roles to a data set.

    The data contains the relevant portion of attributes from the
    core.personas table. We have some more logic than simply grabbing
    the flags from the dict like only allowing admin privileges in a
    realm if access to the realm is already granted.

    Note that this also works on non-personas (i.e. dicts of is_* flags).

    :param introspection_only: If True the result should only be used to
      take an extrinsic look on a persona and not the determine the privilege
      level of the data set passed.
    """
    ret = {"anonymous"}
    if session['is_active'] or introspection_only:
        ret.add("persona")
    elif not introspection_only:
        return ret
    realms = {"cde", "event", "ml", "assembly"}
    for realm in realms:
        if session["is_{}_realm".format(realm)]:
            ret.add(realm)
            if session.get("is_{}_admin".format(realm)):
                ret.add("{}_admin".format(realm))
    if "cde" in ret:
        if session.get("is_core_admin"):
            ret.add("core_admin")
        if session.get("is_meta_admin"):
            ret.add("meta_admin")
        if session["is_member"]:
            ret.add("member")
            if session.get("is_searchable"):
                ret.add("searchable")
    if "ml" in ret:
        if session.get("is_cdelokal_admin"):
            ret.add("cdelokal_admin")
    if "cde_admin" in ret:
        if session.get("is_finance_admin"):
            ret.add("finance_admin")
    return ret


# The following droids are exempt from lockdown to keep our infrastructure
# working
INFRASTRUCTURE_DROIDS: Set[str] = {'resolve'}


def droid_roles(identity: str) -> Set[Role]:
    """Resolve droid identity to a complete set of roles.

    Currently this is rather trivial, but could be more involved in the
    future if more API capabilities are added to the DB.

    :param identity: The name for the API functionality, e.g. ``resolve``.
    """
    ret = {'anonymous', 'droid', f'droid_{identity}'}
    if identity in INFRASTRUCTURE_DROIDS:
        ret.add('droid_infra')
    return ret


# The following dict defines the hierarchy of realms. This has direct impact on
# the admin privileges: An admin of a specific realm can only query and edit
# members of that realm, who are not member of another realm implying that
# realm.
#
# This defines an ordering on the realms making the realms a partially
# ordered set. Later we will use the notion of maximal elements of subsets,
# which are those which have nothing above them. To clarify this two examples:
#
# * in the set {'assembly', 'event', 'ml'} the elements 'assembly' and
#   'event' are maximal
#
# * in the set {'cde', 'assembly', 'event'} only 'cde' is maximal
#
# This dict is not evaluated recursively, so recursively implied realms must
# be added manually to make the implication transitive.
REALM_INHERITANCE: Dict[Realm, Set[Role]] = {
    'cde': {'event', 'assembly', 'ml'},
    'event': {'ml'},
    'assembly': {'ml'},
    'ml': set(),
}


def extract_realms(roles: Set[Role]) -> Set[Realm]:
    """Get the set of realms from a set of user roles.

    When checking admin privileges, we must often check, if the user's realms
    are a subset of some other set of realms. To help with this, this function
    helps with this task, by extracting only the actual realms from a user's
    set of roles.

    :param roles: All roles of a user
    :return: The realms the user is member of
    """
    return roles & REALM_INHERITANCE.keys()


def implied_realms(realm: Realm) -> Set[Realm]:
    """Get additional realms implied by membership in one realm

    :param realm: The name of the realm to check
    :return: A set of the names of all implied realms
    """
    return REALM_INHERITANCE.get(realm, set())


def implying_realms(realm: Realm) -> Set[Realm]:
    """Get all realms where membership implies the given realm.

    This can be used to determine the realms in which a user must *not* be to be
    listed in a specific realm or be edited by its admins.

    :param realm: The realm to search implying realms for
    :return: A set of all realms implying
    """
    return set(r for r, implied in REALM_INHERITANCE.items()
               if realm in implied)


def privilege_tier(roles: Set[Role], conjunctive: bool = False
                   ) -> List[Set[Role]]:
    """Required admin privilege relative to a persona (signified by its roles)

    Basically this answers the question: If a user has access to the passed
    realms, what kind of admin privilege does one need to perform an
    operation on the user?

    First we determine the relevant subset of the passed roles. These are
    the maximal elements according to the realm inheritance. These apex
    roles regulate the access.

    The answer now depends on whether the operation pertains to some
    specific realm (editing a user is the prime example here) or affects all
    realms (creating a user is the corresponding example). This distinction
    is controlled by the conjunctive parameter, if it is True the operation
    lies in the intersection of all realms.

    Note that core admins and meta admins are always allowed access.

    :returns: List of sets of admin roles. Any of these sets is sufficient.
    """
    # Get primary user realms (those, that don't imply other realms)
    relevant = roles & REALM_INHERITANCE.keys()
    if relevant:
        implied_roles = set.union(*(
            REALM_INHERITANCE.get(k, set()) for k in relevant))
        relevant -= implied_roles
    if conjunctive:
        ret = [{realm + "_admin" for realm in relevant},
               {"core_admin"}]
    else:
        ret = list({realm + "_admin"} for realm in relevant)
        ret += [{"core_admin"}]
    return ret


#: Creating a persona requires one to supply values for nearly all fields,
#: although in some realms they are meaningless. Here we provide a base skeleton
#: which can be used, so that these realms do not need to have any knowledge of
#: these fields.
PERSONA_DEFAULTS = {
    'is_cde_realm': False,
    'is_event_realm': False,
    'is_ml_realm': False,
    'is_assembly_realm': False,
    'is_member': False,
    'is_searchable': False,
    'is_active': True,
    'title': None,
    'name_supplement': None,
    'gender': None,
    'birthday': None,
    'telephone': None,
    'mobile': None,
    'address_supplement': None,
    'address': None,
    'postal_code': None,
    'location': None,
    'country': None,
    'birth_name': None,
    'address_supplement2': None,
    'address2': None,
    'postal_code2': None,
    'location2': None,
    'country2': None,
    'weblink': None,
    'specialisation': None,
    'affiliation': None,
    'timeline': None,
    'interests': None,
    'free_form': None,
    'trial_member': None,
    'decided_search': None,
    'bub_search': None,
    'foto': None,
    'paper_expuls': None,
}

#: Set of possible values for ``ntype`` in
#: :py:meth:`RequestState.notify`. Must conform to the regex
#: ``[a-z]+``.
NOTIFICATION_TYPES: Set[NotificationType] = {"success", "info", "question",
                                             "warning", "error"}

#: The form field name used for the anti CSRF token.
#: It should be added to all data modifying form using the
#: util.anti_csrf_token template macro and is check by the application.
ANTI_CSRF_TOKEN_NAME = "_anti_csrf"
#: The value the anti CSRF token is expected to have
ANTI_CSRF_TOKEN_PAYLOAD = "_anti_csrf_check"

#: Map of available privilege levels to those present in the SQL database
#: (where we have less differentiation for the sake of simplicity).
#:
#: This is an ordered dict, so that we can select the highest privilege
#: level.
if TYPE_CHECKING:
    role_map_type = collections.OrderedDict[Role, str]
else:
    role_map_type = collections.OrderedDict

#: List of all roles we consider admin roles. Changes in these roles must be
#: approved by two meta admins in total.
ADMIN_KEYS = {"is_meta_admin", "is_core_admin", "is_cde_admin",
              "is_finance_admin", "is_event_admin", "is_ml_admin",
              "is_assembly_admin", "is_cdelokal_admin"}

#: List of all admin roles who actually have a corresponding realm with a user role.
REALM_ADMINS = {"core_admin", "cde_admin", "event_admin", "ml_admin", "assembly_admin"}

DB_ROLE_MAPPING: role_map_type = collections.OrderedDict((
    ("meta_admin", "cdb_admin"),
    ("core_admin", "cdb_admin"),
    ("cde_admin", "cdb_admin"),
    ("ml_admin", "cdb_admin"),
    ("assembly_admin", "cdb_admin"),
    ("event_admin", "cdb_admin"),
    ("finance_admin", "cdb_admin"),
    ("cdelokal_admin", "cdb_admin"),

    ("searchable", "cdb_member"),
    ("member", "cdb_member"),
    ("cde", "cdb_member"),
    ("assembly", "cdb_member"),

    ("event", "cdb_persona"),
    ("ml", "cdb_persona"),
    ("persona", "cdb_persona"),
    ("droid", "cdb_persona"),

    ("anonymous", "cdb_anonymous"),
))


# All roles available to non-driod users. Can be used to create dummy users
# with all roles, like for `cdedb.script` or `cdedb.frontend.cron`.
ALL_ROLES: Set[Role] = set(DB_ROLE_MAPPING) - {"droid"}


def roles_to_db_role(roles: Set[Role]) -> str:
    """Convert a set of application level roles into a database level role."""
    for role in DB_ROLE_MAPPING:
        if role in roles:
            return DB_ROLE_MAPPING[role]

    raise RuntimeError(n_("Could not determine any db role."))


ADMIN_VIEWS_COOKIE_NAME = "enabled_admin_views"

#: every admin view with one admin role per row (except of genesis)
ALL_ADMIN_VIEWS: Set[AdminView] = {
    "meta_admin",
    "core_user", "core",
    "cde_user", "past_event", "ml_mgmt_cde", "ml_mod_cde",
    "finance",
    "event_user", "event_mgmt", "event_orga", "ml_mgmt_event", "ml_mod_event",
    "ml_user", "ml_mgmt", "ml_mod",
    "ml_mgmt_cdelokal", "ml_mod_cdelokal",
    "assembly_user", "assembly_mgmt", "assembly_presider",
    "ml_mgmt_assembly", "ml_mod_assembly",
    "genesis"}

ALL_MOD_ADMIN_VIEWS: Set[AdminView] = {
    "ml_mod", "ml_mod_cde", "ml_mod_event", "ml_mod_cdelokal",
    "ml_mod_assembly"}

ALL_MGMT_ADMIN_VIEWS: Set[AdminView] = {
    "ml_mgmt", "ml_mgmt_cde", "ml_mgmt_event", "ml_mgmt_cdelokal",
    "ml_mgmt_assembly"}


def roles_to_admin_views(roles: Set[Role]) -> Set[AdminView]:
    """ Get the set of available admin views for a user with given roles."""
    result: Set[Role] = set()
    if "meta_admin" in roles:
        result |= {"meta_admin"}
    if "core_admin" in roles:
        result |= {"core", "core_user", "cde_user", "event_user",
                   "assembly_user", "ml_user"}
    if "cde_admin" in roles:
        result |= {"cde_user", "past_event", "ml_mgmt_cde", "ml_mod_cde"}
    if "finance_admin" in roles:
        result |= {"finance"}
    if "event_admin" in roles:
        result |= {"event_user", "event_mgmt", "event_orga", "ml_mgmt_event",
                   "ml_mod_event"}
    if "ml_admin" in roles:
        result |= {"ml_user", "ml_mgmt", "ml_mod"}
    if "cdelokal_admin" in roles:
        result |= {"ml_mgmt_cdelokal", "ml_mod_cdelokal"}
    if "assembly_admin" in roles:
        result |= {"assembly_user", "assembly_mgmt", "assembly_presider",
                   "ml_mgmt_assembly", "ml_mod_assembly"}
    if roles & ({'core_admin'} | set(
            "{}_admin".format(realm)
            for realm in REALM_SPECIFIC_GENESIS_FIELDS)):
        result |= {"genesis"}
    return result


#: Version tag, so we know that we don't run out of sync with exported event
#: data. This has to be incremented whenever the event schema changes.
#: If the partial export and import are unaffected the minor version may be
#: incremented.
#: If you increment this, it must be incremented in make_offline_vm.py as well.
EVENT_SCHEMA_VERSION = (15, 3)

#: Default number of course choices of new event course tracks
DEFAULT_NUM_COURSE_CHOICES = 3

#: All columns deciding on the current status of a persona
PERSONA_STATUS_FIELDS = (
    "is_active", "is_meta_admin", "is_core_admin", "is_cde_admin",
    "is_finance_admin", "is_event_admin", "is_ml_admin", "is_assembly_admin",
    "is_cde_realm", "is_event_realm", "is_ml_realm", "is_assembly_realm",
    "is_cdelokal_admin", "is_member", "is_searchable", "is_archived", "is_purged")

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_CORE_FIELDS = PERSONA_STATUS_FIELDS + (
    "id", "username", "display_name", "family_name", "given_names",
    "title", "name_supplement")

#: Names of columns associated to a cde (former)member
PERSONA_CDE_FIELDS = PERSONA_CORE_FIELDS + (
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country", "birth_name",
    "address_supplement2", "address2", "postal_code2", "location2",
    "country2", "weblink", "specialisation", "affiliation", "timeline",
    "interests", "free_form", "balance", "decided_search", "trial_member",
    "bub_search", "foto", "paper_expuls")

#: Names of columns associated to an event user. This should be a subset of
#: :py:data:`PERSONA_CDE_FIELDS` to facilitate upgrading of event users to
#: members.
PERSONA_EVENT_FIELDS = PERSONA_CORE_FIELDS + (
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country")

#: Names of columns associated to a ml user.
PERSONA_ML_FIELDS = PERSONA_CORE_FIELDS

#: Names of columns associated to an assembly user.
PERSONA_ASSEMBLY_FIELDS = PERSONA_CORE_FIELDS

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_ALL_FIELDS = PERSONA_CDE_FIELDS + ("notes",)

#: Fields of a persona creation case.
GENESIS_CASE_FIELDS = (
    "id", "ctime", "username", "given_names", "family_name",
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country", "birth_name", "attachment_hash",
    "realm", "notes", "case_status", "reviewer")

# The following dict defines, which additional fields are required for genesis
# request for distinct realms. Additionally, it is used to define for which
# realms genesis requrests are allowed
REALM_SPECIFIC_GENESIS_FIELDS: Dict[Realm, Tuple[str, ...]] = {
    "ml": tuple(),
    "event": ("gender", "birthday", "telephone", "mobile",
              "address_supplement", "address", "postal_code", "location",
              "country"),
    "cde": ("gender", "birthday", "telephone", "mobile",
            "address_supplement", "address", "postal_code", "location",
            "country", "birth_name", "attachment_hash"),
}

# This overrides the more general PERSONA_DEFAULTS dict with some realm-specific
# defaults for genesis account creation.
GENESIS_REALM_OVERRIDE = {
    'event': {
        'is_cde_realm': False,
        'is_event_realm': True,
        'is_assembly_realm': False,
        'is_ml_realm': True,
        'is_member': False,
        'is_searchable': False,
    },
    'ml': {
        'is_cde_realm': False,
        'is_event_realm': False,
        'is_assembly_realm': False,
        'is_ml_realm': True,
        'is_member': False,
        'is_searchable': False,
    },
    'cde': {
        'is_cde_realm': True,
        'is_event_realm': True,
        'is_assembly_realm': True,
        'is_ml_realm': True,
        'is_member': True,
        'is_searchable': False,
        'trial_member': True,
        'decided_search': False,
        'bub_search': False,
        'paper_expuls': True,
    }
}

# This defines which fields are available for which realm. They are cumulative.
PERSONA_FIELDS_BY_REALM: Dict[Role, Set[str]] = {
    'persona': {
        "display_name", "family_name", "given_names", "title",
        "name_supplement", "notes"
    },
    'ml': set(),
    'assembly': set(),
    'event': {
        "gender", "birthday", "telephone", "mobile", "address_supplement",
        "address", "postal_code", "location", "country"
    },
    'cde': {
        "birth_name", "weblink", "specialisation", "affiliation", "timeline",
        "interests", "free_form", "is_searchable", "paper_expuls",
        "address_supplement2", "address2", "postal_code2", "location2",
        "country2",
    }
}

# Some of the above fields cannot be edited by the users themselves.
# These are defined here.
RESTRICTED_FIELDS_BY_REALM: Dict[Role, Set[str]] = {
    'persona': {
        "notes",
    },
    'ml': set(),
    'assembly': set(),
    'event': {
        "gender", "birthday",
    },
    'cde': {
        "is_searchable",
    }
}


def get_persona_fields_by_realm(roles: Set[Role], restricted: bool = True
                                ) -> Set[str]:
    """Helper to retrieve the appropriate fields for a user.

    :param restricted: If True, only return fields the user may change
        themselves, i.e. remove the restricted fields."""
    ret: Set[str] = set()
    for role, fields in PERSONA_FIELDS_BY_REALM.items():
        if role in roles:
            ret |= fields
            if restricted:
                ret -= RESTRICTED_FIELDS_BY_REALM[role]
    return ret


#: Fields of a pending privilege change.
PRIVILEGE_CHANGE_FIELDS = (
    "id", "ctime", "ftime", "persona_id", "submitted_by", "status",
    "is_meta_admin", "is_core_admin", "is_cde_admin",
    "is_finance_admin", "is_event_admin", "is_ml_admin",
    "is_assembly_admin", "is_cdelokal_admin", "notes", "reviewer")

#: Fields for institutions of events
INSTITUTION_FIELDS = ("id", "title", "shortname")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "shortname", "institution", "description",
                     "tempus", "participant_info")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "institution", "description", "shortname", "registration_start",
    "registration_soft_limit", "registration_hard_limit", "iban", "nonmember_surcharge",
    "orga_address", "registration_text", "mail_text", "use_additional_questionnaire",
    "notes", "participant_info", "offline_lock", "is_visible",
    "is_course_list_visible", "is_course_state_visible", "is_participant_list_visible",
    "is_course_assignment_visible", "is_cancelled", "is_archived", "lodge_field",
    "camping_mat_field", "course_room_field")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "shortname", "part_begin",
                     "part_end", "fee", "waitlist_field")

#: Fields of a track where courses can happen
COURSE_TRACK_FIELDS = ("id", "part_id", "title", "shortname", "num_choices",
                       "min_choices", "sortkey")

#: Fields of an extended attribute associated to an event entity
FIELD_DEFINITION_FIELDS = (
    "id", "event_id", "field_name", "kind", "association", "entries", "checkin",
)

#: Fields of a modifier for an event_parts fee.
FEE_MODIFIER_FIELDS = ("id", "part_id", "modifier_name", "amount", "field_id")

#: Fields of a concluded course
PAST_COURSE_FIELDS = ("id", "pevent_id", "nr", "title", "description")

#: Fields of a course associated to an event organized via the CdEDB
COURSE_FIELDS = ("id", "event_id", "title", "description", "nr", "shortname",
                 "instructors", "max_size", "min_size", "notes", "fields")

#: Fields specifying in which part a course is available
COURSE_SEGMENT_FIELDS = ("course_id", "track_id", "is_active")

#: Fields of a registration to an event organized via the CdEDB
REGISTRATION_FIELDS = (
    "id", "persona_id", "event_id", "notes", "orga_notes", "payment",
    "parental_agreement", "mixed_lodging", "checkin", "list_consent", "fields",
    "real_persona_id", "amount_paid", "amount_owed")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "status",
                            "lodgement_id", "is_camping_mat")

#: Fields of a registration which are specific for each course track
REGISTRATION_TRACK_FIELDS = ("registration_id", "track_id", "course_id",
                             "course_instructor")

#: Fields of a lodgement group
LODGEMENT_GROUP_FIELDS = ("id", "event_id", "title")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "title", "regular_capacity",
                    "camping_mat_capacity", "notes", "group_id", "fields")

# Fields of a row in a questionnaire.
# (This can be displayed in different places according to `kind`).
QUESTIONNAIRE_ROW_FIELDS = ("field_id", "pos", "title", "info",
                            "input_size", "readonly", "default_value", "kind")

#: Fields for a stored event query.
STORED_EVENT_QUERY_FIELDS = (
    "id", "event_id", "query_name", "scope", "serialized_query")

#: Fields of a mailing list entry (that is one mailinglist)
MAILINGLIST_FIELDS = (
    "id", "title", "address", "local_part", "domain", "description",
    "mod_policy", "notes", "attachment_policy", "ml_type",
    "subject_prefix", "maxsize", "is_active", "event_id", "registration_stati",
    "assembly_id")

#: Fields of a mailinglist which may be changed by all moderators, even restricted ones
RESTRICTED_MOD_ALLOWED_FIELDS = {
    "description", "mod_policy", "notes", "attachment_policy", "subject_prefix",
    "maxsize"}

#: Fields of a mailinglist which require full moderator access to be changed
FULL_MOD_REQUIRING_FIELDS = {
    'registration_stati'}

#: Fields of a mailinglist which may be changed by (full) moderators
MOD_ALLOWED_FIELDS = RESTRICTED_MOD_ALLOWED_FIELDS | FULL_MOD_REQUIRING_FIELDS

#: Fields of an assembly
ASSEMBLY_FIELDS = ("id", "title", "shortname", "description", "presider_address",
                   "signup_end", "is_active", "notes")

#: Fields of a ballot
BALLOT_FIELDS = (
    "id", "assembly_id", "title", "description", "vote_begin", "vote_end",
    "vote_extension_end", "extended", "use_bar", "abs_quorum", "rel_quorum", "quorum",
    "votes", "is_tallied", "notes")

#: Fields of an attachment in the assembly realm (attached either to an
#: assembly or a ballot)
ASSEMBLY_ATTACHMENT_FIELDS = ("id", "assembly_id", "ballot_id")

ASSEMBLY_ATTACHMENT_VERSION_FIELDS = ("attachment_id", "version", "title",
                                      "authors", "filename", "ctime", "dtime",
                                      "file_hash")

#: Fields of a semester
ORG_PERIOD_FIELDS = (
    "id", "billing_state", "billing_done", "billing_count",
    "ejection_state", "ejection_done", "ejection_count", "ejection_balance",
    "balance_state", "balance_done", "balance_trialmembers", "balance_total",
    "archival_notification_state", "archival_notification_count",
    "archival_notification_done", "archival_state", "archival_count", "archival_done",
    "semester_done")

#: Fielsd of an expuls
EXPULS_PERIOD_FIELDS = (
    "id", "addresscheck_state", "addresscheck_done", "addresscheck_count")

#: Fields of one direct debit permit
LASTSCHRIFT_FIELDS = (
    "id", "submitted_by", "persona_id", "amount", "iban",
    "account_owner", "account_address", "granted_at", "revoked_at", "notes")

#: Fields of one interaction on behalf of a direct debit permit
LASTSCHRIFT_TRANSACTION_FIELDS = (
    "id", "submitted_by", "lastschrift_id", "period_id", "status", "amount",
    "issued_at", "processed_at", "tally")

#: Datatype and Association of special purpose event fields
EVENT_FIELD_SPEC: Dict[
    str, Tuple[Set[const.FieldDatatypes], Set[const.FieldAssociations]]] = {
    'lodge_field': ({const.FieldDatatypes.str}, {const.FieldAssociations.registration}),
    'camping_mat_field': (
        {const.FieldDatatypes.bool}, {const.FieldAssociations.registration}),
    'course_room_field': ({const.FieldDatatypes.str}, {const.FieldAssociations.course}),
    'waitlist': ({const.FieldDatatypes.int}, {const.FieldAssociations.registration}),
    'fee_modifier': (
        {const.FieldDatatypes.bool}, {const.FieldAssociations.registration}),
}

LOG_FIELDS_COMMON = ("codes", "persona_id", "submitted_by", "change_note", "offset",
                     "length", "time_start", "time_stop")

EPSILON = 10 ** (-6)  #:

#: Timestamp which lies in the future. Make a constant so we do not have to
#: hardcode the value otherwere
FUTURE_TIMESTAMP = datetime.datetime(9996, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
