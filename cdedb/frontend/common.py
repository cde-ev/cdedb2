#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic.
"""

import abc
import collections
import copy
import csv
import datetime
import decimal
import email
import email.charset
import email.encoders
import email.header
import email.mime
import email.mime.application
import email.mime.audio
import email.mime.image
import email.mime.multipart
import email.mime.text
import email.utils
import enum
import functools
import io
import json
import logging
import pathlib
import re
import shutil
import smtplib
import subprocess
import tempfile
import threading
import typing
import urllib.error
import urllib.parse
from email.mime.nonmultipart import MIMENonMultipart
from secrets import token_hex
from typing import (
    IO, AbstractSet, Any, AnyStr, Callable, ClassVar, Collection, Container, Dict,
    Generator, ItemsView, Iterable, List, Mapping, MutableMapping, Optional, Sequence,
    Set, Tuple, Type, TypeVar, Union, cast, overload,
)

import babel.dates
import babel.numbers
import bleach
import jinja2
import mailmanclient
import markdown
import markdown.extensions.toc
import werkzeug
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.utils
import werkzeug.wrappers
from typing_extensions import Literal, Protocol

import cdedb.database.constants as const
import cdedb.query as query_mod
import cdedb.validation as validate
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.common import AbstractBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.common import (
    ALL_MGMT_ADMIN_VIEWS, ALL_MOD_ADMIN_VIEWS, ANTI_CSRF_TOKEN_NAME,
    ANTI_CSRF_TOKEN_PAYLOAD, REALM_SPECIFIC_GENESIS_FIELDS, CdEDBMultiDict, CdEDBObject,
    CustomJSONEncoder, EntitySorter, Error, Notification, NotificationType, PathLike,
    RequestState, Role, User, ValidationWarning, _tdelta, asciificator,
    compute_checkdigit, decode_parameter, encode_parameter, glue, json_serialize,
    make_proxy, make_root_logger, merge_dicts, n_, now, roles_to_db_role, unwrap,
    xsorted,
)
from cdedb.config import BasicConfig, Config, SecretsConfig
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.devsamples import HELD_MESSAGE_SAMPLE
from cdedb.enums import ENUMS_DICT

_LOGGER = logging.getLogger(__name__)
_BASICCONF = BasicConfig()


S = TypeVar('S')
T = TypeVar('T')


class Response(werkzeug.wrappers.Response):
    """Wrapper around werkzeugs Response to handle displaynote cookie.

    This is a pretty thin wrapper, but essential so our magic cookie
    gets cleared and no stale notifications remain.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.delete_cookie("displaynote")


class BaseApp(metaclass=abc.ABCMeta):
    """Additional base class under :py:class:`AbstractFrontend` which will be
    inherited by :py:class:`cdedb.frontend.application.Application`.
    """
    realm: ClassVar[str]

    def __init__(self, configpath: PathLike = None, *args: Any,
                 **kwargs: Any) -> None:
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        # initialize logging
        if hasattr(self, 'realm') and self.realm:
            logger_name = "cdedb.frontend.{}".format(self.realm)
            logger_file = self.conf[f"{self.realm.upper()}_FRONTEND_LOG"]
        else:
            logger_name = "cdedb.frontend"
            logger_file = self.conf["FRONTEND_LOG"]
        make_root_logger(
            logger_name, logger_file, self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.logger = logging.getLogger(logger_name)  # logger are thread-safe!
        self.logger.debug("Instantiated {} with configpath {}.".format(
            self, configpath))
        # local variable to prevent closure over secrets
        url_parameter_salt = secrets["URL_PARAMETER_SALT"]
        self.decode_parameter = (
            lambda target, name, param, persona_id: decode_parameter(
                url_parameter_salt, target, name, param,
                persona_id))

        def local_encode(
                target: str, name: str, param: str, persona_id: Optional[int],
                timeout: Optional[_tdelta] = self.conf["PARAMETER_TIMEOUT"]
        ) -> str:
            return encode_parameter(url_parameter_salt, target, name,
                                    param, persona_id, timeout)

        self.encode_parameter = local_encode

    def encode_notification(self, rs: RequestState, ntype: NotificationType,
                            nmessage: str, nparams: CdEDBObject = None) -> str:
        """Wrapper around :py:meth:`encode_parameter` for notifications.

        The message format is A--B--C--D, with

        * A is the notification type, conforming to '[a-z]+'
        * B is the length of the notification message
        * C is the notification message
        * D is the parameter dict to be substituted in the message
          (json-encoded).
        """
        nparams = nparams or {}
        message = "{}--{}--{}--{}".format(ntype, len(nmessage), nmessage,
                                          json_serialize(nparams))
        return self.encode_parameter(
            '_/notification', 'displaynote', message,
            persona_id=rs.user.persona_id,
            timeout=self.conf["UNCRITICAL_PARAMETER_TIMEOUT"])

    def decode_notification(self, rs: RequestState, note: str
                            ) -> Union[Notification, Tuple[None, None, None]]:
        """Inverse wrapper to :py:meth:`encode_notification`."""
        timeout, message = self.decode_parameter(
            '_/notification', 'displaynote', note, rs.user.persona_id)
        if not message:
            return None, None, None
        parts = message.split("--")
        ntype = parts[0]
        length = int(parts[1])
        remainder = "--".join(parts[2:])
        nmessage = remainder[:length]
        nparams = json.loads(remainder[length + 2:])
        return ntype, nmessage, nparams

    def redirect(self, rs: RequestState, target: str,
                 params: CdEDBObject = None, anchor: str = None
                 ) -> werkzeug.Response:
        """Create a response which diverts the user. Special care has to be
        taken not to lose any notifications.
        """
        params = params or {}
        if rs.retrieve_validation_errors() and not rs.notifications:
            rs.notify("error", n_("Failed validation."))
        url = cdedburl(rs, target, params, force_external=True)
        if anchor is not None:
            url += "#" + anchor
        ret = basic_redirect(rs, url)
        if rs.notifications:
            notifications = [self.encode_notification(rs, ntype, nmessage,
                                                      nparams)
                             for ntype, nmessage, nparams in rs.notifications]
            ret.set_cookie("displaynote", json_serialize(notifications))
        return ret


# Ignore the capitalization error in function name sanitize_None.
# noinspection PyPep8Naming
def sanitize_None(data: Optional[T]) -> Union[str, T]:
    """Helper to let jinja convert all ``None`` into empty strings for display
    purposes; thus we needn't be careful in this regard. (This is
    coherent with our policy that NULL and the empty string on SQL level
    shall have the same meaning).
    """
    if data is None:
        return ""
    else:
        return data


@overload
def safe_filter(val: None) -> None: ...


@overload
def safe_filter(val: str) -> jinja2.Markup: ...


def safe_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to mark a string as safe.

    This prevents autoescaping of this entity. To be used for dynamically
    generated code we insert into the templates. It is basically equal to
    Jinja's builtin ``|safe``-Filter, but additionally takes care about None
    values.
    """
    if val is None:
        return None
    return jinja2.Markup(val)


def date_filter(val: Union[datetime.date, str, None],
                formatstr: str = "%Y-%m-%d", lang: str = None,
                verbosity: str = "medium",
                passthrough: bool = False) -> Optional[str]:
    """Custom jinja filter to format ``datetime.date`` objects.

    :param formatstr: Formatting used, if no l10n happens.
    :param lang: If not None, then localize to the passed language.
    :param verbosity: Controls localized formatting. Takes one of the
      following values: short, medium, long and full.
    :param passthrough: If True return strings unmodified.
    """
    if val is None or val == '' or not isinstance(val, datetime.date):
        if passthrough and isinstance(val, str) and val:
            return val
        return None
    if lang:
        return babel.dates.format_date(val, locale=lang, format=verbosity)
    else:
        return val.strftime(formatstr)


def datetime_filter(val: Union[datetime.datetime, str, None],
                    formatstr: str = "%Y-%m-%d %H:%M (%Z)", lang: str = None,
                    verbosity: str = "medium",
                    passthrough: bool = False) -> Optional[str]:
    """Custom jinja filter to format ``datetime.datetime`` objects.

    :param formatstr: Formatting used, if no l10n happens.
    :param lang: If not None, then localize to the passed language.
    :param verbosity: Controls localized formatting. Takes one of the
      following values: short, medium, long and full.
    :param passthrough: If True return strings unmodified.
    """
    if val is None or val == '' or not isinstance(val, datetime.datetime):
        if passthrough and isinstance(val, str) and val:
            return val
        return None
    if val.tzinfo is not None:
        val = val.astimezone(_BASICCONF["DEFAULT_TIMEZONE"])
    else:
        _LOGGER.warning("Found naive datetime object {}.".format(val))
    if lang:
        return babel.dates.format_datetime(val, locale=lang, format=verbosity)
    else:
        return val.strftime(formatstr)


@overload
def money_filter(val: None, currency: str = "EUR", lang: str = "de"
                 ) -> None: ...


@overload
def money_filter(val: decimal.Decimal, currency: str = "EUR", lang: str = "de"
                 ) -> str: ...


def money_filter(val: Optional[decimal.Decimal], currency: str = "EUR",
                 lang: str = "de") -> Optional[str]:
    """Custom jinja filter to format ``decimal.Decimal`` objects.

    This is for values representing monetary amounts.
    """
    if val is None:
        return None

    return babel.numbers.format_currency(val, currency, locale=lang)


@overload
def decimal_filter(val: None, lang: str) -> None: ...


@overload
def decimal_filter(val: float, lang: str) -> str: ...


def decimal_filter(val: Optional[float], lang: str) -> Optional[str]:
    """Cutom jinja filter to format floating point numbers."""
    if val is None:
        return None

    return babel.numbers.format_decimal(val, locale=lang)


@overload
def cdedbid_filter(val: None) -> None: ...


@overload
def cdedbid_filter(val: int) -> str: ...


def cdedbid_filter(val: Optional[int]) -> Optional[str]:
    """Custom jinja filter to format persona ids with a check digit. Every user
    visible id should be formatted with this filter. The check digit is
    one of the letters between 'A' and 'K' to make a clear distinction
    between the numeric id and the check digit.
    """
    if val is None:
        return None
    return "DB-{}-{}".format(val, compute_checkdigit(val))


@overload
def iban_filter(val: None) -> None: ...


@overload
def iban_filter(val: str) -> str: ...


def iban_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for displaying IBANs in nice to read blocks."""
    if val is None:
        return None
    else:
        val = val.strip().replace(" ", "")
        return " ".join(val[x:x + 4] for x in range(0, len(val), 4))


@overload
def hidden_iban_filter(val: None) -> None: ...


@overload
def hidden_iban_filter(val: str) -> str: ...


def hidden_iban_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for hiding IBANs in nice to read blocks."""
    if val is None:
        return None
    else:
        val = val[:4] + "*" * (len(val) - 8) + val[-4:]
        return iban_filter(val)


@overload
def escape_filter(val: None) -> None: ...


@overload
def escape_filter(val: str) -> jinja2.Markup: ...


def escape_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to reconcile escaping with the finalize method
    (which suppresses all ``None`` values and thus mustn't be converted to
    strings first).

    .. note:: Actually this returns a jinja specific 'safe string' which
      will remain safe when operated on. This means for example that the
      linebreaks filter has to make the string unsafe again, before it can
      work.
    """
    if val is None:
        return None
    else:
        return jinja2.escape(val)


LATEX_ESCAPE_REGEX = (
    (re.compile(r'\\'), r'\\textbackslash '),
    (re.compile(r'([{}_#%&$])'), r'\\\1'),
    (re.compile(r'~'), r'\~{}'),
    (re.compile(r'\^'), r'\^{}'),
    (re.compile(r'"'), r"''"),
)


@overload
def tex_escape_filter(val: None) -> None: ...


@overload
def tex_escape_filter(val: str) -> str: ...


def tex_escape_filter(val: Optional[str]) -> Optional[str]:
    """Custom jinja filter for escaping LaTeX-relevant charakters."""
    if val is None:
        return None
    else:
        val = str(val)
        for pattern, replacement in LATEX_ESCAPE_REGEX:
            val = pattern.sub(replacement, val)
        return val


class CustomEscapingJSONEncoder(CustomJSONEncoder):
    """Extension to CustomJSONEncoder defined in cdedb.common, that
    escapes all strings for safely embedding the
    resulting JSON string into an HTML <script> tag.

    Inspired by https://github.com/simplejson/simplejson/blob/
    dd0f99d6431b5e75293369f5554a1396f8ae6251/simplejson/encoder.py#L378
    """

    def encode(self, o: Any) -> str:
        # Override JSONEncoder.encode to avoid bypasses of interencode()
        # in original version
        chunks = self.iterencode(o, True)
        if self.ensure_ascii:
            return ''.join(chunks)
        else:
            return u''.join(chunks)

    def iterencode(self, o: Any, _one_shot: bool = False
                   ) -> Generator[str, None, None]:
        chunks = super().iterencode(o, _one_shot)
        for chunk in chunks:
            chunk = chunk.replace('/', '\\x2f')
            chunk = chunk.replace('&', '\\x26')
            chunk = chunk.replace('<', '\\x3c')
            chunk = chunk.replace('>', '\\x3e')
            yield chunk


def json_filter(val: Any) -> str:
    """Custom jinja filter to create json representation of objects. This is
    intended to allow embedding of values into generated javascript code.

    The result of this method does not need to be escaped -- more so if
    escaped, the javascript execution will probably fail.
    """
    return json.dumps(val, cls=CustomEscapingJSONEncoder)


@overload
def enum_filter(val: None, enum: Type[enum.Enum]) -> None: ...


@overload
def enum_filter(val: int, enum: Type[enum.Enum]) -> str: ...


def enum_filter(val: Optional[int], enum: Type[enum.Enum]) -> Optional[str]:
    """Custom jinja filter to convert enums to something printable.

    This exists mainly because of the possibility of None values.
    """
    if val is None:
        return None
    return str(enum(val))


@overload
def genus_filter(val: None, female: str, male: str, unknown: Optional[str]
                 ) -> None: ...


@overload
def genus_filter(val: int, female: str, male: str,
                 unknown: Optional[str]) -> Optional[str]: ...


def genus_filter(val: Optional[int], female: str, male: str,
                 unknown: str = None) -> Optional[str]:
    """Custom jinja filter to select gendered form of a string."""
    if val is None:
        return None
    if unknown is None:
        unknown = female
    if val == const.Genders.female:
        return female
    elif val == const.Genders.male:
        return male
    else:
        return unknown


# noinspection PyPep8Naming
def stringIn_filter(val: Any, alist: Collection[Any]) -> bool:
    """Custom jinja filter to test if a value is in a list, but requiring
    equality only on string representation.

    This has to be an explicit filter becaus jinja does not support list
    comprehension.
    """
    return str(val) in (str(x) for x in alist)


def querytoparams_filter(val: query_mod.Query) -> CdEDBObject:
    """Custom jinja filter to convert query into a parameter dict
    which can be used to create a URL of the query.

    This could probably be done in jinja, but this would be pretty
    painful.
    """
    params: CdEDBObject = {}
    for field in val.fields_of_interest:
        params['qsel_{}'.format(field)] = True
    for field, op, value in val.constraints:
        params['qop_{}'.format(field)] = op.value
        if (isinstance(value, collections.Iterable)
                and not isinstance(value, str)):
            # TODO: Get separator from central place
            #  (also used in validation._query_input)
            params['qval_{}'.format(field)] = ','.join(str(x) for x in value)
        else:
            params['qval_{}'.format(field)] = value
    for entry, postfix in zip(val.order,
                              ("primary", "secondary", "tertiary")):
        field, ascending = entry
        params['qord_{}'.format(postfix)] = field
        params['qord_{}_ascending'.format(postfix)] = ascending
    params['is_search'] = True
    return params


@overload
def linebreaks_filter(val: None, replacement: str) -> None: ...


@overload
def linebreaks_filter(val: Union[str, jinja2.Markup],
                      replacement: str) -> jinja2.Markup: ...


def linebreaks_filter(val: Union[None, str, jinja2.Markup],
                      replacement: str = "<br>") -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert line breaks to <br>.

    This filter escapes the input value (if required), replaces the linebreaks
    and marks the output as safe html.
    """
    if val is None:
        return None
    # escape the input. This function consumes an unescaped string or a
    # jinja2.Markup safe html object and returns an escaped string.
    val = jinja2.escape(val)
    return val.replace('\n', jinja2.Markup(replacement))


#: bleach internals are not thread-safe, so we have to be a bit defensive
#: w.r.t. threads
BLEACH_CLEANER = threading.local()


def get_bleach_cleaner() -> bleach.sanitizer.Cleaner:
    """Constructs bleach cleaner appropiate to untrusted user content.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    cleaner = getattr(BLEACH_CLEANER, 'cleaner', None)
    if cleaner:
        return cleaner
    tags = [
        'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li',
        'ol', 'strong', 'ul',
        # customizations
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'colgroup', 'col', 'tr', 'th',
        'thead', 'table', 'tbody', 'td', 'hr', 'p', 'span', 'div', 'pre', 'tt',
        'sup', 'sub', 'br', 'u', 'dl', 'dt', 'dd', 'details', 'summary']
    attributes = {
        'a': ['href', 'title'],
        'abbr': ['title'],
        'acronym': ['title'],
        # customizations
        '*': ['class', 'id'],
        'col': ['width'],
        'thead': ['valign'],
        'tbody': ['valign'],
        'table': ['border'],
        'th': ['colspan', 'rowspan'],
        'td': ['colspan', 'rowspan'],
        'details': ['open'],
    }
    cleaner = bleach.sanitizer.Cleaner(tags=tags, attributes=attributes)
    BLEACH_CLEANER.cleaner = cleaner
    return cleaner


@overload
def bleach_filter(val: None) -> None: ...


@overload
def bleach_filter(val: str) -> jinja2.Markup: ...


def bleach_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert sanitize html with bleach."""
    if val is None:
        return None
    return jinja2.Markup(get_bleach_cleaner().clean(val))


#: The Markdown parser has internal state, so we have to be a bit defensive
#: w.r.t. threads
MARKDOWN_PARSER = threading.local()


def md_id_wrapper(val: str, sep: str) -> str:
    """
    Wrap the markdown toc slugify function to attach an ID prefix.

    :param val: String to be made URL friendly.
    :param sep: String to be used instead of Whitespace.
    """

    id_prefix = "CDEDB_MD_"

    return id_prefix + markdown.extensions.toc.slugify(val, sep)


def get_markdown_parser() -> markdown.Markdown:
    """Constructs a markdown parser for general use.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    md = getattr(MARKDOWN_PARSER, 'md', None)

    if md is None:
        extension_configs = {
            "toc": {
                "baselevel": 4,
                "permalink": True,
                "slugify": md_id_wrapper,
            },
            'smarty': {
                'substitutions': {
                    'left-single-quote': '&sbquo;',
                    'right-single-quote': '&lsquo;',
                    'left-double-quote': '&bdquo;',
                    'right-double-quote': '&ldquo;',
                },
            },
        }
        md = markdown.Markdown(extensions=["extra", "sane_lists", "smarty", "toc"],
                               extension_configs=extension_configs)  # type: ignore

        MARKDOWN_PARSER.md = md
    else:
        md.reset()
    return md


@overload
def md_filter(val: None) -> None: ...


@overload
def md_filter(val: str) -> jinja2.Markup: ...


def md_filter(val: Optional[str]) -> Optional[jinja2.Markup]:
    """Custom jinja filter to convert markdown to html."""
    if val is None:
        return None
    md = get_markdown_parser()
    return bleach_filter(md.convert(val))


@jinja2.environmentfilter
def sort_filter(env: jinja2.Environment, value: Iterable[T],
                reverse: bool = False, attribute: Any = None) -> List[T]:
    """Sort an iterable using `xsorted`, using correct collation.

    TODO: With Jinja 2.11, make_multi_attrgetter should be used
    instead, since it allows to provide multiple sorting criteria.

    :param reverse: Sort descending instead of ascending.
    :param attribute: When sorting objects or dicts, an attribute or
        key to sort by. Can use dot notation like ``"address.city"``.
        Can be a list of attributes like ``"age,name"``.
    """
    key_func = jinja2.filters.make_attrgetter(env, attribute)
    return xsorted(value, key=key_func, reverse=reverse)


def dictsort_filter(value: Mapping[T, S],
                    reverse: bool = False) -> List[Tuple[T, S]]:
    """Sort a dict and yield (key, value) pairs.

    Because python dicts are unsorted you may want to use this function to
    order them by key.
    """
    return xsorted(value.items(), key=lambda x: x[0], reverse=reverse)


def set_filter(value: Iterable[T]) -> Set[T]:
    """
    A simple filter to construct a Python set from an iterable object. Just
    like Jinja's builtin "list" filter, but for sets.
    """
    return set(value)


def xdictsort_filter(value: Mapping[T, S], attribute: str,
                     reverse: bool = False) -> List[Tuple[T, S]]:
    """Allow sorting by an arbitrary attribute of the value.

    Jinja only provides sorting by key or entire value. Also Jinja does
    not allow comprehensions or lambdas, hence we have to use this.

    This obviously only works if the values allow access by key.

    :param attribute: name of the attribute
    """
    key = lambda item: item[1].get(attribute)
    return xsorted(value.items(), key=key, reverse=reverse)


def keydictsort_filter(value: Mapping[T, S], sortkey: Callable[[Any], Any],
                       reverse: bool = False) -> List[Tuple[T, S]]:
    """Sort a dicts items by their value."""
    return xsorted(value.items(), key=lambda e: sortkey(e[1]), reverse=reverse)


def map_dict_filter(d: Dict[str, str],
                      processing: Callable[[Any], str]
                      ) -> ItemsView[str, str]:
    """
    Processes the values of some string using processing function

    :param processing: A function to be applied on the dict values
    :return: The dict with its values replaced with the processed values
    """
    return {k: processing(v) for k, v in d.items()}.items()


def enum_entries_filter(enum: enum.EnumMeta, processing: Callable[[Any], str] = None,
                        raw: bool = False,
                        prefix: str = "") -> List[Tuple[int, str]]:
    """
    Transform an Enum into a list of of (value, string) tuple entries. The
    string is piped trough the passed processing callback function to get the
    human readable and translated caption of the value.

    :param processing: A function to be applied on the value's string
        representation before adding it to the result tuple. Typically this is
        gettext()
    :param raw: If this is True, the enum entries are passed to processing as
        is, otherwise they are converted to str first.
    :param prefix: A prefix to prepend to the string output of every entry.
    :return: A list of tuples to be used in the input_checkboxes or
        input_select macros.
    """
    if processing is None:
        processing = lambda x: x
    if raw:
        pre = lambda x: x
    else:
        pre = str
    to_sort = ((entry.value, prefix + processing(pre(entry)))  # type: ignore
               for entry in enum)
    return xsorted(to_sort)


def dict_entries_filter(items: List[Tuple[Any, Mapping[T, S]]],
                        *args: T) -> List[Tuple[S, ...]]:
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of specified fields of the value dict.

    Example::

        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> dict_entries_filter(items, 'name', 'active')
        [('a', True), ('b', False)]

    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :param args: Additional positional arguments describing which keys of
      the dicts should be inserted in the resulting tuple
    :return: A list of tuples (e.g. to be used in the input_checkboxes or
      input_select macros), built from the selected fields of the dicts
    """
    return [tuple(value[k] for k in args) for key, value in items]


def xdict_entries_filter(items: Sequence[Tuple[Any, CdEDBObject]], *args: str,
                         include: Container[str] = None
                         ) -> List[Tuple[str, ...]]:
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of strings with specified format. Each entry of the resulting
    tuples is built by applying the item's value dict to a format string.

    Example::
        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> xdict_entries_filter(items, '{id}', '{name} -- {active}')
        [('1', 'a -- True'), ('2', 'b -- False')]

    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :param args: Additional positional arguments, which are format strings
      for the resulting tuples. They can use named format specifications to
      access the dicts' fields.
    :param include: An iteratable to search for items' keys. Only items with
      their key being in `include` are included in the results list
    :return: A list of tuples (e.g. to be used in the input_checkboxes or
      input_select macros), built from the selected fields of the dicts
    """
    return [tuple(k.format(**value) for k in args)
            for key, value in items
            if (include is None or key in include)]


#: Dictionary of custom filters we make available in the templates.
JINJA_FILTERS = {
    'date': date_filter,
    'datetime': datetime_filter,
    'money': money_filter,
    'decimal': decimal_filter,
    'cdedbid': cdedbid_filter,
    'iban': iban_filter,
    'hidden_iban': hidden_iban_filter,
    'escape': escape_filter,
    'e': escape_filter,
    'json': json_filter,
    'stringIn': stringIn_filter,
    'querytoparams': querytoparams_filter,
    'genus': genus_filter,
    'linebreaks': linebreaks_filter,
    'map_dict': map_dict_filter,
    'md': md_filter,
    'enum': enum_filter,
    'sort': sort_filter,
    'dictsort': dictsort_filter,
    'xdictsort': xdictsort_filter,
    'keydictsort': keydictsort_filter,
    's': safe_filter,
    'set': set_filter,
    'tex_escape': tex_escape_filter,
    'te': tex_escape_filter,
    'enum_entries': enum_entries_filter,
    'dict_entries': dict_entries_filter,
    'xdict_entries': xdict_entries_filter,
}


class AbstractFrontend(BaseApp, metaclass=abc.ABCMeta):
    """Common base class for all frontends."""
    #: to be overridden by children

    def __init__(self, configpath: PathLike = None, *args: Any,
                 **kwargs: Any) -> None:
        super().__init__(configpath, *args, **kwargs)
        self.template_dir = pathlib.Path(self.conf["REPOSITORY_PATH"], "cdedb",
                                         "frontend", "templates")
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)),
            extensions=['jinja2.ext.i18n', 'jinja2.ext.do', 'jinja2.ext.loopcontrols'],
            finalize=sanitize_None, autoescape=True, auto_reload=self.conf["CDEDB_DEV"])
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.jinja_env.globals.update({
            'now': now,
            'nbsp': "\u00A0",
            'query_mod': query_mod,
            'glue': glue,
            'enums': ENUMS_DICT,
            'encode_parameter': self.encode_parameter,
            'staticurl': functools.partial(staticurl,
                                           version=self.conf["GIT_COMMIT"][:8]),
            'docurl': docurl,
            'CDEDB_OFFLINE_DEPLOYMENT': self.conf["CDEDB_OFFLINE_DEPLOYMENT"],
            'CDEDB_DEV': self.conf["CDEDB_DEV"],
            'UNCRITICAL_PARAMETER_TIMEOUT': self.conf[
                "UNCRITICAL_PARAMETER_TIMEOUT"],
            'ANTI_CSRF_TOKEN_NAME': ANTI_CSRF_TOKEN_NAME,
            'ANTI_CSRF_TOKEN_PAYLOAD': ANTI_CSRF_TOKEN_PAYLOAD,
            'GIT_COMMIT': self.conf["GIT_COMMIT"],
            'I18N_LANGUAGES': self.conf["I18N_LANGUAGES"],
            'ALL_MOD_ADMIN_VIEWS': ALL_MOD_ADMIN_VIEWS,
            'ALL_MGMT_ADMIN_VIEWS': ALL_MGMT_ADMIN_VIEWS,
            'EntitySorter': EntitySorter,
            'roles_allow_genesis_management':
                lambda roles: roles & ({'core_admin'} | set(
                    "{}_admin".format(realm)
                    for realm in REALM_SPECIFIC_GENESIS_FIELDS)),
        })
        self.jinja_env_tex = self.jinja_env.overlay(
            autoescape=False,
            block_start_string="<<%",
            block_end_string="%>>",
            variable_start_string="<<<",
            variable_end_string=">>>",
            comment_start_string="<<#",
            comment_end_string="#>>",
        )
        self.jinja_env_mail = self.jinja_env.overlay(
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.policies['ext.i18n.trimmed'] = True  # type: ignore
        # Always provide all backends -- they are cheap
        self.assemblyproxy = make_proxy(AssemblyBackend(configpath))
        self.cdeproxy = make_proxy(CdEBackend(configpath))
        self.coreproxy = make_proxy(CoreBackend(configpath))
        self.eventproxy = make_proxy(EventBackend(configpath))
        self.mlproxy = make_proxy(MlBackend(configpath))
        self.pasteventproxy = make_proxy(PastEventBackend(configpath))
        # Provide mailman access
        secrets = SecretsConfig(configpath)
        # local variables to prevent closure over secrets
        mailman_password = secrets["MAILMAN_PASSWORD"]
        mailman_basic_auth_password = secrets["MAILMAN_BASIC_AUTH_PASSWORD"]
        self.get_mailman = lambda: CdEMailmanClient(self.conf, mailman_password,
                                                    mailman_basic_auth_password)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs: RequestState) -> bool:
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    def fill_template(self, rs: RequestState, modus: str, templatename: str,
                      params: CdEDBObject) -> str:
        """Central function for generating output from a template. This
        makes several values always accessible to all templates.

        .. note:: We change the templating syntax for TeX templates since
                  jinjas default syntax is nasty for this.

        :param modus: Type of thing we want to generate; can be one of
          * web,
          * mail,
          * tex,
          * other.
        :param templatename: file name of template without extension
        """

        def _cdedblink(endpoint: str, params: CdEDBObject = None,
                       magic_placeholders: Collection[str] = None) -> str:
            """We don't want to pass the whole request state to the
            template, hence this wrapper.

            :type endpoint: str
            :type params: {str: object}
            :param magic_placeholders: parameter names to insert as magic
                                       placeholders in url
            :type magic_placeholders: [str]
            :rtype: str
            """
            params = params or {}
            return cdedburl(rs, endpoint, params,
                            force_external=(modus != "web"),
                            magic_placeholders=magic_placeholders)

        def _doclink(topic: str, anchor: str = "") -> str:
            """Create link to documentation in non-web templates.

            This should be used to avoid hardcoded links in our templates. To create
            links in web-templates, use docurl in combination with util.href instead.
            """
            if modus == "web":
                raise RuntimeError(n_("Must not be used in web templates."))
            return doclink(rs, label="", topic=topic, anchor=anchor, html=False)

        def _staticlink(path: str, version: str = "") -> str:
            """Create link to static files in non-web templates.

            This should be used to avoid hardcoded links in our templates. To create
            links in web-templates, use staticurl in combination with util.href instead.
            """
            if modus == "web":
                raise RuntimeError(n_("Must not be used in web templates."))
            return staticlink(rs, label="", path=path, version=version, html=False)

        def _show_user_link(user: User, persona_id: int, quote_me: bool = None,
                            event_id: int = None, ml_id: int = None) -> str:
            """Convenience method to create link to user data page.

            This is lengthy otherwise because of the parameter encoding
            and a pretty frequent operation so that it is beneficial to
            have this helper.
            """
            params = {
                'persona_id': persona_id,
                'confirm_id': self.encode_parameter(
                    "core/show_user", "confirm_id", str(persona_id),
                    persona_id=user.persona_id, timeout=None)}
            if quote_me:
                params['quote_me'] = True
            if event_id:
                params['event_id'] = event_id
            if ml_id:
                params['ml_id'] = ml_id
            return cdedburl(rs, 'core/show_user', params)

        def _is_warning(parameter_name: str) -> bool:
            """Determine if a given error is a warning.

            They can be suppressed by the user.
            """
            all_errors = rs.retrieve_validation_errors()
            return all(
                isinstance(kind, ValidationWarning)
                for param, kind in all_errors if param == parameter_name)

        def _has_warnings() -> bool:
            """Determine if there are any warnings among the errors."""
            all_errors = rs.retrieve_validation_errors()
            return any(
                isinstance(kind, ValidationWarning)
                for param, kind in all_errors)

        def _make_backend_checker(rs: RequestState, backend: AbstractBackend,
                                  method_name: str) -> Callable[..., Any]:
            """Provide a checker from the backend(proxy) for the templates.

            This wraps a call to the given backend method, to not require
            access to the backend or the RequestState.
            """
            checker = getattr(backend, method_name)
            if callable(checker):
                return lambda *args, **kwargs: checker(rs, *args, **kwargs)
            else:
                raise AttributeError(n_("Given method is not callable."))

        errorsdict: Dict[Optional[str], List[Exception]] = {}
        for key, value in rs.retrieve_validation_errors():
            errorsdict.setdefault(key, []).append(value)

        # here come the always accessible things promised above
        data = {
            'ambience': rs.ambience,
            'cdedblink': _cdedblink,
            'doclink': _doclink,
            'staticlink': _staticlink,
            'errors': errorsdict,
            'generation_time': lambda: (now() - rs.begin),
            'gettext': rs.gettext,
            'has_warnings': _has_warnings,
            'is_admin': self.is_admin(rs),
            'is_relevant_admin': _make_backend_checker(
                rs, self.mlproxy, method_name="is_relevant_admin"),
            'is_warning': _is_warning,
            'lang': rs.lang,
            'ngettext': rs.ngettext,
            'notifications': rs.notifications,
            'original_request': rs.request,
            'show_user_link': _show_user_link,
            'user': rs.user,
            'values': rs.values,
        }

        # check that default values are not overridden
        if set(data) & set(params):
            raise ValueError(
                n_("Default values cannot be overridden: %(keys)s"),
                {'keys': set(data) & set(params)})
        merge_dicts(data, params)

        if modus == "web":
            jinja_env = self.jinja_env
        elif modus == "mail":
            jinja_env = self.jinja_env_mail
        elif modus == "tex":
            jinja_env = self.jinja_env_tex
        elif modus == "other":
            jinja_env = self.jinja_env
        else:
            raise NotImplementedError(n_("Requested modus does not exists: %(modus)s"),
                                      {'modus': modus})
        tmpl = pathlib.Path(modus, self.realm, f"{templatename}.tmpl")
        # sadly, jinja does not catch nicely if the template exists, so we do this here
        if not (self.template_dir / tmpl).is_file():
            raise ValueError(n_("Template not found: %(file)s"), {'file': tmpl})
        t = jinja_env.get_template(str(tmpl))
        return t.render(**data)

    @staticmethod
    def send_csv_file(rs: RequestState, mimetype: str = 'text/csv',
                      filename: str = None, inline: bool = True, *,
                      path: Union[str, pathlib.Path] = None,
                      afile: IO[AnyStr] = None,
                      data: AnyStr = None) -> Response:
        """Wrapper around :py:meth:`send_file` for CSV files.

        This makes Excel happy by adding a BOM at the beginning of the
        file. All parameters (except for encoding) are as in the wrapped
        method.
        """
        if path is not None:
            path = pathlib.Path(path)
        return AbstractFrontend.send_file(
            rs, mimetype=mimetype, filename=filename, inline=inline, path=path,
            afile=afile, data=data, encoding='utf-8-sig')

    @staticmethod
    def send_file(rs: RequestState, mimetype: str = None, filename: str = None,
                  inline: bool = True, *, path: PathLike = None,
                  afile: IO[AnyStr] = None, data: AnyStr = None,
                  encoding: str = 'utf-8') -> Response:
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :param mimetype: If not None the mime type of the file to be sent.
        :param filename: If not None the default file name used if the user
          tries to save the file to disk
        :param inline: Set content disposition to force display in browser (if
          True) or to force a download box (if False).
        :param afile: should be opened in binary mode
        :param encoding: The character encoding to be uses, if `data` is given
          as str
        """
        if not path and not afile and not data:
            raise ValueError(n_("No input specified."))
        if (path and afile) or (path and data) or (afile and data):
            raise ValueError(n_("Ambiguous input."))

        data_buffer = io.BytesIO()
        if path:
            path = pathlib.Path(path)
            if not path.is_file():
                raise werkzeug.exceptions.NotFound()
            with open(path, 'rb') as f:
                data_buffer.write(f.read())
        elif afile:
            content = afile.read()
            if isinstance(content, str):
                data_buffer.write(content.encode(encoding))
            elif isinstance(content, bytes):
                data_buffer.write(content)
            else:
                raise ValueError(n_("Invalid datatype read from file."))
        elif data:
            if isinstance(data, str):
                data_buffer.write(data.encode(encoding))
            elif isinstance(data, bytes):
                data_buffer.write(data)
            else:
                raise ValueError(n_("Invalid input type."))
        data_buffer.seek(0)

        wrapped_file = werkzeug.wsgi.wrap_file(rs.request.environ, data_buffer)
        extra_args = {}
        if mimetype is not None:
            extra_args['mimetype'] = mimetype
        headers = []
        disposition = "inline" if inline else "attachment"
        if filename is not None:
            disposition += '; filename="{}"'.format(filename)
        headers.append(('Content-Disposition', disposition))
        headers.append(('X-Generation-Time', str(now() - rs.begin)))
        return Response(wrapped_file, direct_passthrough=True, headers=headers,
                        **extra_args)

    @staticmethod
    def send_json(rs: RequestState, data: Any) -> Response:
        """Slim helper to create json responses."""
        response = Response(json_serialize(data),
                            mimetype='application/json')
        response.headers.add('X-Generation-Time', str(now() - rs.begin))
        return response

    def send_query_download(self, rs: RequestState,
                            result: Collection[CdEDBObject], fields: List[str],
                            kind: str, filename: str,
                            substitutions: Mapping[
                                str, Mapping[Any, Any]] = None
                            ) -> Response:
        """Helper to send download of query result.

        :param fields: List of fields the output should have. Commaseparated
            fields will be split up.
        :param kind: Can be either `'csv'` or `'json'`.
        :param filename: The extension will be added automatically depending on
            the kind specified.
        """
        if not fields:
            raise ValueError(n_("Cannot download query result without fields"
                                " of interest."))
        fields: List[str] = sum((csvfield.split(',') for csvfield in fields), [])
        filename += f".{kind}"
        if kind == "csv":
            csv_data = csv_output(result, fields, substitutions=substitutions)
            return self.send_csv_file(
                rs, data=csv_data, inline=False, filename=filename)
        elif kind == "json":
            json_data = query_result_to_json(
                result, fields, substitutions=substitutions)
            return self.send_file(
                rs, data=json_data, inline=False, filename=filename)
        else:
            raise ValueError(
                n_("Unknown download kind {kind}."), {"kind": kind})

    def render(self, rs: RequestState, templatename: str,
               params: CdEDBObject = None) -> werkzeug.Response:
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTML responses.
        """
        params = params or {}
        # handy, should probably survive in a commented HTML portion
        if 'debugstring' not in params and self.conf["CDEDB_DEV"]:
            debugstring = (
                f"We have is_multithreaded={rs.request.is_multithread};"
                f" is_multiprocess={rs.request.is_multiprocess};"
                f" base_url={rs.request.base_url}; cookies={rs.request.cookies};"
                f" url={rs.request.url}; is_secure={rs.request.is_secure};"
                f" method={rs.request.method}; remote_addr={rs.request.remote_addr};"
                f" values={rs.values}; ambience={rs.ambience};"
                f" errors={rs.retrieve_validation_errors()}; time={now()}")

            params['debugstring'] = debugstring
        if rs.retrieve_validation_errors() and not rs.notifications:
            rs.notify("error", n_("Failed validation."))
        if self.conf["LOCKDOWN"]:
            rs.notify("info", n_("The database currently undergoes "
                                 "maintenance and is unavailable."))
        # A nonce to mark safe <script> tags in context of the CSP header
        csp_nonce = token_hex(12)
        params['csp_nonce'] = csp_nonce

        html = self.fill_template(rs, "web", templatename, params)
        response = Response(html, mimetype='text/html')
        response.headers.add('X-Generation-Time', str(now() - rs.begin))

        # Add CSP header to disallow scripts, styles, images and objects from
        # other domains. This is part of XSS mitigation
        csp_header_template = glue(
            "default-src 'self';",
            "script-src 'unsafe-inline' 'self' https: 'nonce-{}';",
            "style-src 'self' 'unsafe-inline';",
            "img-src *")
        response.headers.add('Content-Security-Policy',
                             csp_header_template.format(csp_nonce))
        return response

    # TODO use new typing feature to accurately define the following:
    # from typing import TypedDict
    # Attachment = TypedDict(
    #     "Attachment", {'path': PathLike, 'filename': str, 'mimetype': str,
    #                    'file': IO}, total=False)
    Attachment = Dict[str, str]

    def do_mail(self, rs: RequestState, templatename: str,
                headers: MutableMapping[str, Union[str, Collection[str]]],
                params: CdEDBObject = None,
                attachments: Collection[Attachment] = None) -> Optional[str]:
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        Some words about email trouble. Bounced mails go by default to a
        special address ``bounces@cde-ev.de``, which will be a list not
        managed via the DB. For mailinglists the return path will be a
        list specific bounce address which delivers the bounces to the
        moderators.

        :param headers: mandatory headers to supply are To and Subject
        :param attachments: Each dict describes one attachment. The possible
          keys are path (a ``str``), file (a file like), mimetype (a ``str``),
          filename (a ``str``).
        :returns: see :py:meth:`_send_mail` for details, we automatically
          store the path in ``rs``
        """
        params = params or {}
        params['headers'] = headers
        text = self.fill_template(rs, "mail", templatename, params)
        msg = self._create_mail(text, headers, attachments)
        ret = self._send_mail(msg)
        if ret:
            # This is mostly intended for the test suite.
            rs.notify("info", n_("Stored email to hard drive at %(path)s"),
                      {'path': ret})
        return ret

    def _create_mail(self, text: str,
                     headers: MutableMapping[str, Union[str, Collection[str]]],
                     attachments: Optional[Collection[Attachment]],
                     ) -> Union[email.message.Message,
                                email.mime.multipart.MIMEMultipart]:
        """Helper for actual email instantiation from a raw message."""
        defaults = {"From": self.conf["DEFAULT_SENDER"],
                    "Prefix": self.conf["DEFAULT_PREFIX"],
                    "Reply-To": self.conf["DEFAULT_REPLY_TO"],
                    "Return-Path": self.conf["DEFAULT_RETURN_PATH"],
                    "Cc": tuple(),
                    "Bcc": tuple(),
                    "domain": self.conf["MAIL_DOMAIN"],
                    }
        merge_dicts(headers, defaults)
        if headers["From"] == headers["Reply-To"]:
            del headers["Reply-To"]
        msg = email.mime.text.MIMEText(text)
        email.encoders.encode_quopri(msg)
        del msg['Content-Transfer-Encoding']
        msg['Content-Transfer-Encoding'] = 'quoted-printable'
        # we want quoted-printable, but without encoding all the spaces
        # however at the end of lines the standard requires spaces to be
        # encoded hence we have to be a bit careful (encoding is a pain!)
        # 'quoted-printable' ensures we only get str here:
        payload: str = msg.get_payload()
        payload = re.sub('=20(.)', r' \1', payload)
        # do this twice for adjacent encoded spaces
        payload = re.sub('=20(.)', r' \1', payload)
        msg.set_payload(payload)
        if attachments:
            container = email.mime.multipart.MIMEMultipart()
            container.attach(msg)
            for attachment in attachments:
                container.attach(self._create_attachment(attachment))
            # put the container in place as message to send
            msg = container  # type: ignore
        for header in ("To", "Cc", "Bcc"):
            nonempty = {x for x in headers[header] if x}
            if nonempty != set(headers[header]):
                self.logger.warning("Empty values zapped in email recipients.")
            if headers[header]:
                msg[header] = ", ".join(nonempty)
        for header in ("From", "Reply-To", "Return-Path"):
            msg[header] = headers[header]
        subject = headers["Prefix"] + " " + headers['Subject']  # type: ignore
        msg["Subject"] = subject
        msg["Message-ID"] = email.utils.make_msgid(
            domain=self.conf["MAIL_DOMAIN"])
        msg["Date"] = email.utils.format_datetime(now())
        return msg

    @staticmethod
    def _create_attachment(attachment: Attachment) -> MIMENonMultipart:
        """Helper instantiating an attachment via the email module.

        :param attachment: see :py:meth:`do_mail` for a description of keys
        """
        mimetype = attachment.get('mimetype') or 'application/octet-stream'
        maintype, subtype = mimetype.split('/', 1)
        if not attachment.get('file') and not attachment.get('path'):
            raise ValueError(n_("No input provided."))
        if attachment.get('file'):
            # noinspection PyUnresolvedReferences
            data = attachment['file'].read()  # type: ignore
        else:
            if maintype == "text":
                with open(attachment['path'], 'r') as ft:
                    data = ft.read()
            else:
                with open(attachment['path'], 'rb') as fb:
                    data = fb.read()
        # Only support common types
        factories = {
            'application': email.mime.application.MIMEApplication,
            'audio': email.mime.audio.MIMEAudio,
            'image': email.mime.image.MIMEImage,
            'text': email.mime.text.MIMEText,
        }
        ret = factories[maintype](data, _subtype=subtype)
        if attachment.get('filename'):
            ret.add_header('Content-Disposition', 'attachment',
                           filename=attachment['filename'])
        return ret

    def _send_mail(self, msg: email.message.Message) -> Optional[str]:
        """Helper for getting an email onto the wire.

        :returns: Name of the file the email was saved in -- however this
          happens only in development mode. This is intended for consumption
          by the test suite.
        """
        ret = None
        if not msg["To"] and not msg["Cc"] and not msg["Bcc"]:
            self.logger.warning("No recipients for mail. Dropping it.")
            return None
        if not self.conf["CDEDB_DEV"]:
            s = smtplib.SMTP(self.conf["MAIL_HOST"])
            s.send_message(msg)
            s.quit()
        else:
            with tempfile.NamedTemporaryFile(mode='w', prefix="cdedb-mail-",
                                             suffix=".txt", delete=False) as f:
                f.write(str(msg))
                self.logger.debug("Stored mail to {}.".format(f.name))
                ret = f.name
        self.logger.info("Sent email with subject '{}' to '{}'".format(
            msg['Subject'], msg['To']))
        return ret

    def redirect_show_user(self, rs: RequestState, persona_id: int,
                           quote_me: bool = None) -> werkzeug.Response:
        """Convenience function to redirect to a user detail page.

        The point is, that encoding the ``confirm_id`` parameter is
        somewhat lengthy and only necessary because of our paranoia.
        """
        cid = self.encode_parameter(
            "core/show_user", "confirm_id", str(persona_id),
            persona_id=rs.user.persona_id, timeout=None)
        params = {'confirm_id': cid, 'persona_id': persona_id}
        if quote_me is not None:
            params['quote_me'] = True
        return self.redirect(rs, 'core/show_user', params=params)

    @staticmethod
    def notify_return_code(rs: RequestState, code: Union[int, bool, None],
                           success: str = n_("Change committed."),
                           info: str = n_("Change pending."),
                           error: str = n_("Change failed.")) -> None:
        """Small helper to issue a notification based on a return code.

        We allow some flexibility in what type of return code we accept. It
        may be a boolean (with the obvious meanings), an integer (specifying
        the number of changed entries, and negative numbers for entries with
        pending review) or None (signalling failure to acquire something).

        :param success: Affirmative message for positive return codes.
        :param pending: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            rs.notify("error", error)
        elif code is True or code > 0:
            rs.notify("success", success)
        elif code < 0:
            rs.notify("info", info)
        else:
            raise RuntimeError(n_("Impossible."))

    def safe_compile(self, rs: RequestState, target_file: str, cwd: PathLike,
                     runs: int, errormsg: Optional[str]) -> pathlib.Path:
        """Helper to compile latex documents in a safe way.

        This catches exepctions during compilation and displays a more helpful
        error message instead.

        :param target_file: name of the file to compile.
        :param cwd: Path of the target file.
        :param runs: number of times LaTeX is run (for references etc.)
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :returns: Path to the compiled pdf.
        """
        if target_file.endswith('.tex'):
            pdf_file = "{}.pdf".format(target_file[:-4])
        else:
            pdf_file = "{}.pdf".format(target_file)
        pdf_path = pathlib.Path(cwd, pdf_file)

        args = ("lualatex", "-interaction", "batchmode", target_file)
        self.logger.info("Invoking {}".format(args))
        try:
            for _ in range(runs):
                subprocess.run(args, cwd=cwd, check=True,
                               stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            if pdf_path.exists():
                self.logger.debug(
                    "Deleting corrupted file {}".format(pdf_path))
                pdf_path.unlink()
            self.logger.debug("Exception \"{}\" caught and handled.".format(e))
            if self.conf["CDEDB_DEV"]:
                tstamp = round(now().timestamp())
                backup_path = "/tmp/cdedb-latex-error-{}.tex".format(tstamp)
                self.logger.info("Copying source file to {}".format(
                    backup_path))
                shutil.copy2(target_file, backup_path)
            errormsg = errormsg or n_(
                "LaTeX compilation failed. Try downloading the "
                "source files and compiling them manually.")
            rs.notify("error", errormsg)
        return pdf_path

    def latex_compile(self, rs: RequestState, data: str, runs: int = 2,
                      errormsg: str = None) -> Optional[bytes]:
        """Run LaTeX on the provided document.

        This takes care of the necessary temporary files.

        :param runs: number of times LaTeX is run (for references etc.)
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :returns: the compiled document as blob
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_file:
                tmp_file.write(data.encode('utf8'))
                tmp_file.flush()
                path = self.safe_compile(
                    rs, tmp_file.name, tmp_dir, runs=runs, errormsg=errormsg)
                if path.exists():
                    # noinspection PyTypeChecker
                    with open(path, 'rb') as pdf:
                        return pdf.read()
                else:
                    return None

    def serve_latex_document(self, rs: RequestState, data: str, filename: str,
                             runs: int = 2, errormsg: str = None
                             ) -> Optional[Response]:
        """Generate a response from a LaTeX document.

        This takes care of the necessary temporary files.

        :param data: the LaTeX document
        :param filename: name to serve the document as, without extension
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled pdf.
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        """
        if not runs:
            return self.send_file(
                rs, data=data, inline=False,
                filename="{}.tex".format(filename))
        else:
            pdf = self.latex_compile(rs, data, runs=runs, errormsg=errormsg)
            if not pdf:
                return None
            return self.send_file(
                rs, mimetype="application/pdf", data=pdf,
                filename="{}.pdf".format(filename))

    def serve_complex_latex_document(self, rs: RequestState,
                                     tmp_dir: Union[str, pathlib.Path],
                                     work_dir_name: str, tex_file_name: str,
                                     runs: int = 2, errormsg: str = None
                                     ) -> Optional[Response]:
        """Generate a response from a LaTeX document.

        In contrast to :py:meth:`serve_latex_document` this expects that the
        caller takes care of creating a temporary directory and doing the
        setup. Actually this is only usefull if the caller does some
        additional setup (like providing image files).

        Everything has to happen inside a working directory, so the layout
        is as follows::

            tmp_dir
            +------ work_dir
                    |------- tex_file.tex
                    +------- ...

        :param tmp_dir: path of temporary directory
        :param work_dir_name: name of working directory inside temporary
          directory.
        :param tex_file_name: name of the tex file (including extension),
          this will be used to derived the name to use when serving the
          compiled pdf file.
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled
          pdf. More specifically we serve a gzipped tar archive containing
          the working directory.
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        """
        if not runs:
            target = pathlib.Path(tmp_dir, work_dir_name)
            archive = shutil.make_archive(
                str(target), "gztar", base_dir=work_dir_name, root_dir=tmp_dir,
                logger=self.logger)
            if tex_file_name.endswith('.tex'):
                tex_file = "{}.tar.gz".format(tex_file_name[:-4])
            else:
                tex_file = "{}.tar.gz".format(tex_file_name)
            return self.send_file(
                rs, path=archive, inline=False,
                filename=tex_file)
        else:
            work_dir = pathlib.Path(tmp_dir, work_dir_name)
            if tex_file_name.endswith('.tex'):
                pdf_file = "{}.pdf".format(tex_file_name[:-4])
            else:
                pdf_file = "{}.pdf".format(tex_file_name)
            path = self.safe_compile(
                rs, tex_file_name, cwd=work_dir, runs=runs,
                errormsg=errormsg)
            if path.exists():
                return self.send_file(
                    rs, mimetype="application/pdf",
                    path=(work_dir / pdf_file),
                    filename=pdf_file)
            else:
                return None


class CdEMailmanClient(mailmanclient.Client):
    """Custom wrapper around mailmanclient.Client.

    This custom wrapper provides additional functionality needed in multiple frontends.
    Whenever access to the mailman server is needed, this class should be used.
    """
    def __init__(self, conf: Config, mailman_password: str,
                 mailman_basic_auth_password: str):
        """Automatically initializes a client with our custom parameters.

        :param conf: Usually, he config used where this class is instantiated.
        """
        self.conf = conf

        # Initialize base class
        url = f"http://{self.conf['MAILMAN_HOST']}/3.1"
        super().__init__(url, self.conf["MAILMAN_USER"], mailman_password)
        self.template_password = mailman_basic_auth_password

        # Initialize logger. This needs the base class initialization to be done.
        logger_name = "cdedb.frontend.mailmanclient"
        make_root_logger(
            logger_name, self.conf["MAILMAN_LOG"], self.conf["LOG_LEVEL"],
            syslog_level=self.conf["SYSLOG_LEVEL"],
            console_log_level=self.conf["CONSOLE_LOG_LEVEL"])
        self.logger = logging.getLogger(logger_name)
        self.logger.debug("Instantiated {} with configpath {}.".format(
            self, conf._configpath))

    def get_list_safe(self, address: str) -> Optional[
            mailmanclient.restobjects.mailinglist.MailingList]:
        """Return list with standard error handling.

        In contrast to the original function, this does not raise if no list has been
        found, but returns None instead. This is particularly important since list
        creation and deletion are not synced immediately."""
        try:
            return self.get_list(address)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            else:
                raise

    def get_held_messages(self, dblist: CdEDBObject) -> Optional[
            List[mailmanclient.restobjects.held_message.HeldMessage]]:
        """Returns all held messages for mailman lists.

        If the list is not managed by mailman, this function returns None instead.
        """
        if self.conf["CDEDB_OFFLINE_DEPLOYMENT"] or self.conf["CDEDB_DEV"]:
            self.logger.info("Skipping mailman query in dev/offline mode.")
            if self.conf["CDEDB_DEV"]:
                if dblist['domain'] in const.MailinglistDomain.mailman_domains():
                    return HELD_MESSAGE_SAMPLE
        elif dblist['domain'] in const.MailinglistDomain.mailman_domains():
            mmlist = self.get_list_safe(dblist['address'])
            return mmlist.held if mmlist else None
        return None


class Worker(threading.Thread):
    """Customization wrapper around ``threading.Thread``.

    This takes care of initializing a new (basically cloned) request
    state object, containing a separate database connection, so that
    concurrency is no concern.
    """

    def __init__(self, conf: Config, task: Callable[..., bool],
                 rs: RequestState, *args: Any, **kwargs: Any) -> None:
        """
        :param task: Will be called with exactly one argument (the cloned
          request state) until it returns something falsy.
        """
        # noinspection PyProtectedMember
        rrs = RequestState(
            sessionkey=rs.sessionkey, apitoken=rs.apitoken, user=rs.user,
            request=rs.request, notifications=[], mapadapter=rs.urls,
            requestargs=rs.requestargs, errors=[],
            values=copy.deepcopy(rs.values), lang=rs.lang, gettext=rs.gettext,
            ngettext=rs.ngettext, coders=rs._coders, begin=rs.begin)
        # noinspection PyProtectedMember
        secrets = SecretsConfig(conf._configpath)
        connpool = connection_pool_factory(
            conf["CDB_DATABASE_NAME"], DATABASE_ROLES, secrets, conf["DB_PORT"])
        rrs._conn = connpool[roles_to_db_role(rs.user.roles)]
        logger = logging.getLogger("cdedb.frontend.worker")

        def runner() -> None:
            """Implement the actual loop running the task inside the Thread."""
            name = task.__name__
            doc = f" {task.__doc__.splitlines()[0]}" if task.__doc__ else ""
            p_id = rrs.user.persona_id if rrs.user else None
            username = rrs.user.username if rrs.user else None
            logger.debug(
                f"Task `{name}`{doc} started by user {p_id} ({username}).")
            count = 0
            while True:
                try:
                    count += 1
                    if not task(rrs):
                        logger.debug(
                            f"Finished task `{name}` successfully"
                            f" after {count} iterations.")
                        return
                except Exception as e:
                    logger.exception(
                        f"The following error occurred during the {count}th"
                        f" iteration of `{name}: {e}")
                    logger.debug(f"Task {name} aborted.")
                    raise

        super().__init__(target=runner, daemon=False, args=args, kwargs=kwargs)


def reconnoitre_ambience(obj: AbstractFrontend,
                         rs: RequestState) -> Dict[str, CdEDBObject]:
    """Provide automatic lookup of objects in a standard way.

    This creates an ambience dict providing objects for all ids passed
    as part of the URL path. The naming is not predetermined, but as a
    convention the object name should be the parameter named minus the
    '_id' suffix.
    """
    Scout = collections.namedtuple('Scout', ('getter', 'param_name',
                                             'object_name', 'dependencies'))

    def do_assert(x: bool) -> None:
        if not x:
            raise werkzeug.exceptions.BadRequest(
                rs.gettext("Inconsistent request."))

    def attachment_check(a: CdEDBObject) -> None:
        if a['attachment']['ballot_id']:
            do_assert(a['attachment']['ballot_id']
                      == rs.requestargs.get('ballot_id'))
        else:
            do_assert(a['attachment']['assembly_id']
                      == rs.requestargs['assembly_id'])

    scouts = (
        Scout(lambda anid: obj.coreproxy.get_persona(rs, anid), 'persona_id',
              'persona', ()),
        Scout(lambda anid: obj.coreproxy.get_privilege_change(rs, anid),
              'privilege_change_id', 'privilege_change', ()),
        Scout(lambda anid: obj.coreproxy.genesis_get_case(rs, anid),
              'genesis_case_id', 'genesis_case', ()),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift(rs, anid),
              'lastschrift_id', 'lastschrift', ()),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift_transaction(rs, anid),
              'transaction_id', 'transaction',
              ((lambda a: do_assert(a['transaction']['lastschrift_id']
                                    == a['lastschrift']['id'])),)),
        Scout(lambda anid: obj.pasteventproxy.get_institution(rs, anid),
              'institution_id', 'institution', ()),
        Scout(lambda anid: obj.eventproxy.get_event(rs, anid),
              'event_id', 'event', ()),
        Scout(lambda anid: obj.pasteventproxy.get_past_event(rs, anid),
              'pevent_id', 'pevent', ()),
        Scout(lambda anid: obj.eventproxy.get_course(rs, anid),
              'course_id', 'course',
              ((lambda a: do_assert(a['course']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.pasteventproxy.get_past_course(rs, anid),
              'pcourse_id', 'pcourse',
              ((lambda a: do_assert(a['pcourse']['pevent_id']
                                    == a['pevent']['id'])),)),
        Scout(None, 'part_id', None,
              ((lambda a: do_assert(rs.requestargs['part_id']
                                    in a['event']['parts'])),)),
        Scout(lambda anid: obj.eventproxy.get_registration(rs, anid),
              'registration_id', 'registration',
              ((lambda a: do_assert(a['registration']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_lodgement_group(rs, anid),
              'group_id', 'group',
              ((lambda a: do_assert(a['group']['event_id']
                                    == a['event']['id'])),)),
        Scout(lambda anid: obj.eventproxy.get_lodgement(rs, anid),
              'lodgement_id', 'lodgement',
              ((lambda a: do_assert(a['lodgement']['event_id']
                                    == a['event']['id'])),)),
        Scout(None, 'field_id', None,
              ((lambda a: do_assert(rs.requestargs['field_id']
                                    in a['event']['fields'])),)),
        Scout(lambda anid: obj.assemblyproxy.get_attachment(rs, anid),
              'attachment_id', 'attachment', (attachment_check,)),
        Scout(lambda anid: obj.assemblyproxy.get_assembly(rs, anid),
              'assembly_id', 'assembly', ()),
        Scout(lambda anid: obj.assemblyproxy.get_ballot(rs, anid),
              'ballot_id', 'ballot',
              ((lambda a: do_assert(a['ballot']['assembly_id']
                                    == a['assembly']['id'])),)),
        Scout(None, 'candidate_id', None,
              ((lambda a: do_assert(rs.requestargs['candidate_id']
                                    in a['ballot']['candidates'])),)),
        Scout(lambda anid: obj.mlproxy.get_mailinglist(rs, anid),
              'mailinglist_id', 'mailinglist', ()),
    )
    scouts_dict = {s.param_name: s for s in scouts}
    ambience = {}
    for param, value in rs.requestargs.items():
        s = scouts_dict.get(param)
        if s and s.getter:
            try:
                ambience[s.object_name] = s.getter(value)
            except KeyError:
                raise werkzeug.exceptions.NotFound(
                    rs.gettext("Object {param}={value} not found").format(
                        param=param, value=value))
    for param, value in rs.requestargs.items():
        if param in scouts_dict:
            for consistency_checker in scouts_dict[param].dependencies:
                consistency_checker(ambience)
    return ambience


F = TypeVar('F', bound=Callable[..., Any])


def access(*roles: Role, modi: AbstractSet[str] = frozenset(("GET", "HEAD")),
           check_anti_csrf: bool = None) -> Callable[[F], F]:
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :param roles: privilege required (any of the passed)
    :param modi: HTTP methods allowed for this invocation
    :param check_anti_csrf: Control if the anti csrf check should be enabled
        on this endpoint. If not specified, it will be enabled, if "POST" is in
        the allowed methods.
    """
    access_list = set(roles)

    def decorator(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if rs.user.roles & access_list:
                rs.ambience = reconnoitre_ambience(obj, rs)
                return fun(obj, rs, *args, **kwargs)
            else:
                expects_persona = any('droid' not in role
                                      for role in access_list)
                if rs.user.roles == {"anonymous"} and expects_persona:
                    params = {
                        'wants': rs._coders['encode_parameter'](
                            "core/index", "wants", rs.request.url,
                            persona_id=rs.user.persona_id,
                            timeout=obj.conf["UNCRITICAL_PARAMETER_TIMEOUT"])
                    }
                    ret = basic_redirect(rs, cdedburl(rs, "core/index", params))
                    # noinspection PyProtectedMember
                    notifications = json_serialize([
                        rs._coders['encode_notification'](
                            rs, "error", n_("You must login."))])
                    ret.set_cookie("displaynote", notifications)
                    return ret
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("Access denied to {realm}/{endpoint}.").format(
                        realm=obj.__class__.__name__, endpoint=fun.__name__))

        new_fun.access_list = access_list  # type: ignore
        new_fun.modi = modi  # type: ignore
        new_fun.check_anti_csrf = (  # type: ignore
            check_anti_csrf if check_anti_csrf is not None
            else not modi <= {'GET', 'HEAD'} and "anonymous" not in roles)
        return cast(F, new_fun)

    return decorator


PeriodicMethod = Callable[[Any, RequestState, CdEDBObject], CdEDBObject]


class PeriodicJob(Protocol):
    cron: CdEDBObject

    def __call__(self, rs: RequestState, state: CdEDBObject) -> CdEDBObject:
        ...


def periodic(name: str, period: int = 1
             ) -> Callable[[PeriodicMethod], PeriodicJob]:
    """This decorator marks a function of a frontend for periodic execution.

    This just adds a flag and all of the actual work is done by the
    CronFrontend.

    :param name: the name of this job
    :param period: the interval in which to execute this job (e.g. period ==
      2 means every second invocation of the CronFrontend)
    """
    def decorator(fun: PeriodicMethod) -> PeriodicJob:
        fun = cast(PeriodicJob, fun)
        fun.cron = {
            'name': name,
            'period': period,
        }
        return fun

    return decorator


def cdedburl(rs: RequestState, endpoint: str, params: CdEDBObject = None,
             force_external: bool = False,
             magic_placeholders: Collection[str] = None) -> str:
    """Construct an HTTP URL.

    :param endpoint: as defined in :py:data:`cdedb.frontend.paths.CDEDB_PATHS`
    :param magic_placeholders: These are parameter names which behave as if
      the following code would be executed::

          for i, name in enumerate(magic_placeholders):
              params[name] = "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i)

      The use case is that we want to generate string templates of URLs for
      consumption by Javascript code with the possibility of inserting some
      parameters at execution time.
    """
    params = params or {}
    # First handle magic placeholders, this is kind of a hack, but sadly
    # necessary
    if magic_placeholders:
        newparams = copy.deepcopy(params)
        for run in range(1, 10):
            for i, name in enumerate(magic_placeholders):
                # Generate a hopefully unique integer to replace
                newparams[name] = (
                        i * 10 ** (9 * run + 1)
                        + 123456789 * sum(10 ** (9 * j) for j in range(run)))
            attempt = cdedburl(rs, endpoint, newparams,
                               force_external=force_external)
            if any(attempt.count(str(newparams[name])) != 1
                   for name in magic_placeholders):
                continue
            else:
                for i, name in enumerate(magic_placeholders):
                    attempt = attempt.replace(
                        str(newparams[name]),
                        "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i))
                if any(attempt.count(
                        "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i)) != 1
                       for i in range(len(magic_placeholders))):
                    continue
                return attempt
        raise RuntimeError(n_("Magic URL parameter replacement failed."))
    # Second we come to the normal case
    allparams: CdEDBMultiDict = werkzeug.datastructures.MultiDict()
    for arg in rs.requestargs:
        if rs.urls.map.is_endpoint_expecting(endpoint, arg):
            allparams[arg] = rs.requestargs[arg]
    if isinstance(params, werkzeug.datastructures.MultiDict):
        for key in params:
            allparams.setlist(key, params.getlist(key))
    else:
        for key in params:
            allparams[key] = params[key]
    return rs.urls.build(endpoint, allparams, force_external=force_external)


def staticurl(path: str, version: str = "") -> str:
    """Construct an HTTP URL to a static resource (to be found in the static directory).

    We encapsulate this here so moving the directory around causes no pain.

    :param version: If not None, this string is appended to the URL as an URL
        parameter. This can be used to force Browsers to flush their caches on
        code updates.
    """
    ret = str(pathlib.PurePosixPath("/static", path))
    if version:
        ret += '?v=' + version
    return ret


@overload
def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: Literal[True] = True) -> jinja2.Markup: ...


@overload
def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: Literal[False] = False) -> str: ...


def staticlink(rs: RequestState, label: str, path: str, version: str = "",
               html: bool = True) -> Union[jinja2.Markup, str]:
    """Create a link to a static resource.

    This can either create a basic html link or a fully qualified, static https link.

    .. note:: This will be overridden by _staticlink in templates, see fill_template.
    """
    link: Union[jinja2.Markup, str]
    if html:
        return safe_filter(f'<a href="{staticurl(path, version=version)}">{label}</a>')
    else:
        host = rs.urls.get_host("")
        return f"https://{host}{staticurl(path, version=version)}"


def docurl(topic: str, anchor: str = "") -> str:
    """Construct an HTTP URL to a doc page."""
    ret = str(pathlib.PurePosixPath("/doc", topic + ".html"))
    if anchor:
        ret += "#" + anchor
    return ret


@overload
def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: Literal[True] = True) -> jinja2.Markup: ...


@overload
def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: Literal[False] = False) -> str: ...


def doclink(rs: RequestState, label: str, topic: str, anchor: str = "",
            html: bool = True) -> Union[jinja2.Markup, str]:
    """Create a link to our documentation.

    This can either create a basic html link or a fully qualified, static https link.
    .. note:: This will be overridden by _doclink in templates, see fill_template.
    """
    link: Union[jinja2.Markup, str]
    if html:
        return safe_filter(f'<a href="{docurl(topic, anchor=anchor)}">{label}</a>')
    else:
        host = rs.urls.get_host("")
        return f"https://{host}{docurl(topic, anchor=anchor)}"


# noinspection PyPep8Naming
def REQUESTdata(
    *spec: str, _hints: validate.TypeMapping = None
) -> Callable[[F], F]:
    """Decorator to extract parameters from requests and validate them.

    This should always be used, so automatic form filling works as expected.
    The decorator should be the innermost one
    as it needs access to the original "__defaults__" attribute
    to correctly determine types (e.g. "foo: str = None" -> "Optional[str]").
    Alternatively "functools.wraps" can be invoked in a way
    which also updates this attribute if the signature allows this.

    :param spec: Names of the parameters to extract.
        The type of the parameter will be dynamically extracted
        from the type annotations of the decorated function.
        Permitted types are the ones registered in :py:mod:`cdedb.validation`.
        This includes all types from :py:mod:`cdedb.validationtypes`
        as well as some native python types (primitives, datetimes, decimals).
        Additonally the generic types ``Optional[T]`` and ``Collection[T]``
        are valid as a type.
        To extract an encoded parameter one may prepended the name of it 
        with an octothorpe (``#``).
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            hints = _hints or typing.get_type_hints(fun)
            for item in spec:
                if item.startswith('#'):
                    name = item[1:]
                    encoded = True
                else:
                    name = item
                    encoded = False

                if name not in kwargs:

                    if getattr(hints[name], "__origin__", None) is Union:
                        type_, _ = hints[name].__args__
                        optional = True
                    else:
                        type_ = hints[name]
                        optional = False

                    val = rs.request.values.get(name, "")

                    # TODO allow encoded collections?
                    if encoded and val:
                        # only decode if exists
                        # noinspection PyProtectedMember
                        timeout, val = rs._coders['decode_parameter'](
                            "{}/{}".format(obj.realm, fun.__name__),
                            name, val, persona_id=rs.user.persona_id)
                        if timeout is True:
                            rs.notify("warning", n_("Link expired."))
                        if timeout is False:
                            rs.notify("warning", n_("Link invalid."))

                    if getattr(
                        type_, "__origin__", None
                    ) is collections.abc.Collection:
                        type_ = unwrap(type_.__args__)
                        vals = tuple(rs.request.values.getlist(name))
                        if vals:
                            rs.values.setlist(name, vals)
                        else:
                            # TODO should also work normally
                            # We have to be careful, since empty lists are
                            # problematic for the werkzeug MultiDict
                            rs.values[name] = None
                        if optional:
                            kwargs[name] = tuple(
                                check_validation_optional(rs, type_, val, name)
                                for val in vals
                            )
                        else:
                            kwargs[name] = tuple(
                                check_validation(rs, type_, val, name)
                                for val in vals
                            )
                    else:
                        rs.values[name] = val
                        if optional:
                            kwargs[name] = check_validation_optional(
                                rs, type_, val, name)
                        else:
                            kwargs[name] = check_validation(
                                rs, type_, val, name)
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


# noinspection PyPep8Naming
def REQUESTdatadict(*proto_spec: Union[str, Tuple[str, str]]
                    ) -> Callable[[F], F]:
    """Similar to :py:meth:`REQUESTdata`, but doesn't hand down the
    parameters as keyword-arguments, instead packs them all into a dict and
    passes this as ``data`` parameter. This does not do validation since
    this is infeasible in practice.

    :type proto_spec: [str or (str, str)]
    :param proto_spec: Similar to ``spec`` parameter :py:meth:`REQUESTdata`,
      but the only two allowed argument types are ``str`` and
      ``[str]``. Additionally the argument type may be omitted and a default
      of ``str`` is assumed.
    """
    spec = []
    for arg in proto_spec:
        if isinstance(arg, str):
            spec.append((arg, "str"))
        else:
            spec.append(arg)

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            data = {}
            for name, argtype in spec:
                if argtype == "str":
                    data[name] = rs.request.values.get(name, "")
                elif argtype == "[str]":
                    data[name] = tuple(rs.request.values.getlist(name))
                else:
                    raise ValueError(n_("Invalid argtype {t} found.").format(
                        t=repr(argtype)))
                rs.values[name] = data[name]
            return fun(obj, rs, *args, data=data, **kwargs)

        return cast(F, new_fun)

    return wrap


RequestConstraint = Tuple[Callable[[CdEDBObject], bool], Error]


def request_extractor(
        rs: RequestState, spec: validate.TypeMapping,
        constraints: Collection[RequestConstraint] = None) -> CdEDBObject:
    """Utility to apply REQUESTdata later than usual.

    This is intended to bu used, when the parameter list is not known before
    hand. Prime example are the event specific fields of event
    registrations, here the parameter list has to be constructed from data
    retrieved from the backend.

    Sometimes there are interdependencies between the individual
    attributes of the input. It would be best to have them caught by
    the original validators. However these are not easily usable in
    the flexible input setting this function is designed for. So
    instead of a complete rebuild of the validators we add the
    ``constraints`` parameter to perform these checks here. It is a
    list of callables that perform a check and associated errors that
    are reported if the check fails.

    :param spec: handed through to the decorator
    :param constraints: additional constraints that shoud produce
      validation errors
    :returns: dict containing the requested values
    """
    @REQUESTdata(*spec, _hints=spec)
    def fun(_: None, rs: RequestState, **kwargs: Any) -> CdEDBObject:
        if not rs.has_validation_errors():
            for checker, error in constraints or []:
                if not checker(kwargs):
                    rs.append_validation_error(error)
        return kwargs

    return fun(None, rs)


def request_dict_extractor(rs: RequestState,
                           args: Collection[str]) -> CdEDBObject:
    """Utility to apply REQUESTdatadict later than usual.

    Like :py:meth:`request_extractor`.

    :param args: handed through to the decorator
    :returns: dict containing the requested values
    """

    @REQUESTdatadict(*args)
    def fun(_: None, rs: RequestState, data: CdEDBObject) -> CdEDBObject:
        return data

    # This looks wrong. but is correct, as the `REQUESTdatadict` decorator
    # constructs the data parameter `fun` expects.
    return fun(None, rs)  # type: ignore


# noinspection PyPep8Naming
def REQUESTfile(*args: str) -> Callable[[F], F]:
    """Decorator to extract file uploads from requests.

    :param args: Names of file parameters.
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args2: Any,
                    **kwargs: Any) -> Any:
            for name in args:
                if name not in kwargs:
                    kwargs[name] = rs.request.files.get(name, None)
                rs.values[name] = kwargs[name]
            return fun(obj, rs, *args2, **kwargs)

        return cast(F, new_fun)

    return wrap


def event_guard(argname: str = "event_id",
                check_offline: bool = False) -> Callable[[F], F]:
    """This decorator checks the access with respect to a specific event. The
    event is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    The event has to be organized via the DB. Only orgas and privileged
    users are admitted. Additionally this can check for the offline
    lock, so that no modifications happen to locked events.

    :param argname: name of the keyword argument specifying the id
    :param check_offline: defaults to False
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.orga and not obj.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("This page can only be accessed by orgas."))
            if check_offline:
                is_locked = obj.eventproxy.is_offline_locked(rs, event_id=arg)
                if is_locked != obj.conf["CDEDB_OFFLINE_DEPLOYMENT"]:
                    raise werkzeug.exceptions.Forbidden(
                        rs.gettext("This event is locked for offline usage."))
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


def mailinglist_guard(argname: str = "mailinglist_id",
                      allow_moderators: bool = True,
                      requires_privilege: bool = False) -> Callable[[F], F]:
    """This decorator checks the access with respect to a specific
    mailinglist. The list is specified by id which has either to be a
    keyword parameter or the first positional parameter after the
    request state.

    If `allow_moderators` is True, moderators of the mailinglist are allowed,
    otherwise we require a relevant admin for the given mailinglist.

    :param argname: name of the keyword argument specifying the id
    """

    def wrap(fun: F) -> F:
        @functools.wraps(fun)
        def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                    **kwargs: Any) -> Any:
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if allow_moderators:
                if not obj.mlproxy.may_manage(rs, **{argname: arg}):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "This page can only be accessed by the mailinglist’s "
                        "moderators."))
                if (requires_privilege and not
                    obj.mlproxy.may_manage(rs, mailinglist_id=arg, privileged=True)):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "You do not have privileged moderator access and may not change "
                        "subscriptions."))
            else:
                if not obj.mlproxy.is_relevant_admin(rs, **{argname: arg}):
                    raise werkzeug.exceptions.Forbidden(rs.gettext(
                        "This page can only be accessed by appropriate "
                        "admins."))
            return fun(obj, rs, *args, **kwargs)

        return cast(F, new_fun)

    return wrap


def assembly_guard(fun: F) -> F:
    """This decorator checks that the user has privileged access to an assembly.
    """

    @functools.wraps(fun)
    def new_fun(obj: AbstractFrontend, rs: RequestState, *args: Any,
                **kwargs: Any) -> Any:
        if "assembly_id" in kwargs:
            assembly_id = kwargs["assembly_id"]
        else:
            assembly_id = args[0]
        if not obj.assemblyproxy.is_presider(rs, assembly_id=assembly_id):
            raise werkzeug.exceptions.Forbidden(rs.gettext(
                "This page may only be accessed by the assembly's"
                " presiders or assembly admins."))
        return fun(obj, rs, *args, **kwargs)

    return cast(F, new_fun)


def check_validation(rs: RequestState, type_: Type[T], value: Any,
                     name: str = None, **kwargs: Any) -> Optional[T]:
    """Helper to perform parameter sanitization.

    :param type_: type to check for
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    """
    if name is not None:
        ret, errs = validate.validate_check(type_, value, argname=name, **kwargs)
    else:
        ret, errs = validate.validate_check(type_, value, **kwargs)
    rs.extend_validation_errors(errs)
    return ret


def check_validation_optional(rs: RequestState, type_: Type[T], value: Any,
                     name: str = None, **kwargs: Any) -> Optional[T]:
    """Helper to perform parameter sanitization.

    This is similar to :func:`~cdedb.frontend.common.check_validation`
    but also allows optional/falsy values.

    :param type_: type to check for
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    """
    if name is not None:
        ret, errs = validate.validate_check_optional(
            type_, value, argname=name, **kwargs)
    else:
        ret, errs = validate.validate_check_optional(type_, value, **kwargs)
    rs.extend_validation_errors(errs)
    return ret


def basic_redirect(rs: RequestState, url: str) -> werkzeug.Response:
    """Convenience wrapper around :py:func:`construct_redirect`. This should
    be the main thing to use, however it is even more preferable to use
    :py:meth:`BaseApp.redirect`.
    """
    response = construct_redirect(rs.request, url)
    response.headers.add('X-Generation-Time', str(now() - rs.begin))
    return response


def construct_redirect(request: werkzeug.Request,
                       url: str) -> werkzeug.Response:
    """Construct an HTTP redirect. This should use the 303 status
    code. Unfortunately this code is not available for HTTP 1.0, so we fall
    back to an automatic refresh.
    """
    if request.environ['SERVER_PROTOCOL'] == "HTTP/1.0":
        # in case of HTTP 1.0 we cannot use the 303 code
        template = """<!DOCTYPE HTML>
<html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="1;url={url}">
        <title>Redirect</title>
    </head>
    <body>
        You should be redirected now.
        You can also access the target via <a href="{url}">this link</a>.
    </body>
</html>"""
        return Response(template.format(url=urllib.parse.quote(url)),
                        mimetype="text/html")
    else:
        ret = werkzeug.utils.redirect(url, 303)
        ret.delete_cookie("displaynote")
        return ret


def make_postal_address(persona: CdEDBObject) -> List[str]:
    """Prepare address info for formatting.

    Addresses have some specific formatting wishes, so we are flexible
    in that we represent an address to be printed as a list of strings
    each containing one line. The final formatting is now basically join
    on line breaks.
    """
    p = persona
    name = "{} {}".format(p['given_names'], p['family_name'])
    if p['title']:
        name = glue(p['title'], name)
    if p['name_supplement']:
        name = glue(name, p['name_supplement'])
    ret = [name]
    if p['address_supplement']:
        ret.append(p['address_supplement'])
    if p['address']:
        ret.append(p['address'])
    if p['postal_code'] or p['location']:
        ret.append("{} {}".format(p['postal_code'] or '',
                                  p['location'] or ''))
    if p['country']:
        ret.append(p['country'])
    return ret


def make_membership_fee_reference(persona: CdEDBObject) -> str:
    """Generate the desired reference for membership fee payment.

    This is the "Verwendungszweck".
    """
    return "Mitgliedsbeitrag {gn} {fn}, {cdedbid}".format(
        gn=asciificator(persona['given_names']),
        fn=asciificator(persona['family_name']),
        cdedbid=cdedbid_filter(persona['id']),
    )


def make_event_fee_reference(persona: CdEDBObject, event: CdEDBObject) -> str:
    """Generate the desired reference for event fee payment.

    This is the "Verwendungszweck".
    """
    return "Teilnahmebeitrag {event}, {gn} {fn}, {cdedbid}".format(
        event=asciificator(event['title']),
        gn=asciificator(persona['given_names']),
        fn=asciificator(persona['family_name']),
        cdedbid=cdedbid_filter(persona['id'])
    )


def process_dynamic_input(rs: RequestState, existing: Collection[int],
                          spec: validate.TypeMapping,
                          additional: CdEDBObject = None
                          ) -> Dict[int, Optional[CdEDBObject]]:
    """Retrieve information provided by flux tables.

    This returns a data dict to update the database, which includes:
    - existing, mapped to their (validated) input fields (from spec)
    - existing, mapped to None (if they were marked to be deleted)
    - new entries, mapped to their (validated) input fields (from spec)

    :param existing: ids of already existent objects
    :param spec: name of input fields, mapped to their validation
    :param additional: additional keys added to each output object
    """
    delete_flags = request_extractor(rs, {f"delete_{anid}": bool for anid in existing})
    deletes = {anid for anid in existing if delete_flags[f"delete_{anid}"]}
    params: validate.TypeMapping = {
        f"{key}_{anid}": value
        for anid in existing if anid not in deletes
        for key, value in spec.items()
    }
    data = request_extractor(rs, params)
    ret: Dict[int, Optional[CdEDBObject]] = {
        anid: {key: data[f"{key}_{anid}"] for key in spec}
        for anid in existing if anid not in deletes
    }
    for anid in existing:
        if anid in deletes:
            ret[anid] = None
        else:
            ret[anid]['id'] = anid  # type: ignore
    marker = 1
    while marker < 2 ** 10:
        will_create = unwrap(
            request_extractor(rs, {f"create_-{marker}": bool}))
        if will_create:
            params = {f"{key}_-{marker}": value for key, value in spec.items()}
            data = request_extractor(rs, params)
            ret[-marker] = {key: data[f"{key}_-{marker}"] for key in spec}
            if additional:
                ret[-marker].update(additional)  # type: ignore
        else:
            break
        marker += 1
    rs.values['create_last_index'] = marker - 1
    return ret


class CustomCSVDialect(csv.Dialect):
    delimiter = ';'
    quoting = csv.QUOTE_MINIMAL
    quotechar = '"'
    doublequote = True
    lineterminator = '\n'
    escapechar = None


def csv_output(data: Collection[CdEDBObject], fields: Sequence[str],
               writeheader: bool = True, replace_newlines: bool = False,
               substitutions: Mapping[str, Mapping[Any, Any]] = None) -> str:
    """Generate a csv representation of the passed data.

    :param writeheader: If False, no CSV-Header is written.
    :param replace_newlines: If True all line breaks are replaced by several
      spaces.
    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    """
    substitutions = substitutions or {}
    outfile = io.StringIO()
    writer = csv.DictWriter(
        outfile, fields, dialect=CustomCSVDialect())
    if writeheader:
        writer.writeheader()
    for original in data:
        row = {}
        for field in fields:
            value = original[field]
            if field in substitutions:
                value = substitutions[field].get(value, value)
            if replace_newlines and isinstance(value, str):
                value = value.replace('\n', 14 * ' ')
            row[field] = value
        writer.writerow(row)
    return outfile.getvalue()


def query_result_to_json(data: Collection[CdEDBObject], fields: Iterable[str],
                         substitutions: Mapping[
                             str, Mapping[Any, Any]] = None) -> str:
    """Generate a json representation of the passed data.

    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    """
    substitutions = substitutions or {}
    json_data = []
    for original in data:
        row = {}
        for field in fields:
            value = original[field]
            if field in substitutions:
                value = substitutions[field].get(value, value)
            row[field] = value
        json_data.append(row)
    return json_serialize(json_data)


def calculate_db_logparams(offset: Optional[int], length: int
                           ) -> Tuple[Optional[int], int]:
    """Modify the offset and length values used in the frontend to
    allow for guaranteed valid sql queries.
    """
    _offset = offset
    _length = length
    if _offset and _offset < 0:
        # Avoid non-positive lengths
        if -_offset < length:
            _length = _length + _offset
        _offset = 0

    return _offset, _length


def calculate_loglinks(rs: RequestState, total: int,
                       offset: Optional[int], length: int
                       ) -> Dict[str, Union[CdEDBMultiDict, List[CdEDBMultiDict]]]:
    """Calculate the target parameters for the links in the log pagination bar.

    :param total: The total count of log entries
    :param offset: The offset, preprocessed for negative offset values
    :param length: The requested length (not necessarily the shown length)
    """
    # The true offset does represent the acutal count of log entries before
    # the first shown entry. This is done magically, if no offset has been
    # given.
    if offset is None:
        trueoffset = length * ((total - 1) // length) if total != 0 else 0
    else:
        trueoffset = offset

    # Create values sets for the necessary links.
    def new_md() -> CdEDBMultiDict:
        return werkzeug.MultiDict(rs.values)
    loglinks = {
        "first": new_md(),
        "previous": new_md(),
        "current": new_md(),
        "next": new_md(),
        "last": new_md(),
    }
    pre = [new_md() for x in range(3) if trueoffset - x * length > 0]
    post = [new_md() for x in range(3) if trueoffset + (x + 1) * length < total]

    # Fix the offset for each set of values.
    loglinks["first"]["offset"] = "0"
    loglinks["last"]["offset"] = ""
    for x, _ in enumerate(pre):
        pre[x]["offset"] = (trueoffset - (len(pre) - x) * length)
    loglinks["previous"]["offset"] = trueoffset - length
    for x, _ in enumerate(post):
        post[x]["offset"] = trueoffset + (x + 1) * length
    loglinks["next"]["offset"] = trueoffset + length
    loglinks["current"]["offset"] = trueoffset

    # piece everything together
    ret: Dict[str, Union[CdEDBMultiDict, List[CdEDBMultiDict]]]
    ret = dict(**loglinks, **{"pre-current": pre, "post-current": post})
    return ret
