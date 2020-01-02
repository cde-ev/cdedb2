#!/usr/bin/env python3

"""Common code for all frontends. This is a kind of a mixed bag with no
overall topic.
"""

import abc
import collections
import copy
import csv
import datetime
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
import functools
import inspect
import io
import json
import logging
import pathlib
import re
import smtplib
import subprocess
import tempfile
import threading
import types
import urllib.parse

import markdown
import babel.dates
import babel.numbers
import bleach
import docutils.core
import jinja2
import werkzeug
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.utils
import werkzeug.wrappers

from cdedb.config import BasicConfig, Config, SecretsConfig
from cdedb.common import (
    n_, glue, merge_dicts, compute_checkdigit, now, asciificator,
    roles_to_db_role, RequestState, make_root_logger, CustomJSONEncoder,
    json_serialize, ANTI_CSRF_TOKEN_NAME, encode_parameter,
    decode_parameter, EntitySorter)
from cdedb.database import DATABASE_ROLES
from cdedb.database.connection import connection_pool_factory
from cdedb.enums import ENUMS_DICT
import cdedb.validation as validate
import cdedb.database.constants as const
import cdedb.query as query_mod
from cdedb.security import secure_token_hex

_LOGGER = logging.getLogger(__name__)
_BASICCONF = BasicConfig()


class Response(werkzeug.wrappers.Response):
    """Wrapper around werkzeugs Response to handle displaynote cookie.

    This is a pretty thin wrapper, but essential so our magic cookie
    gets cleared and no stale notifications remain.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delete_cookie("displaynote")


class BaseApp(metaclass=abc.ABCMeta):
    """Additional base class under :py:class:`AbstractFrontend` which will be
    inherited by :py:class:`cdedb.frontend.application.Application`.
    """

    def __init__(self, configpath, *args, **kwargs):
        """
        :type configpath: str
        """
        super().__init__(*args, **kwargs)
        self.conf = Config(configpath)
        secrets = SecretsConfig(configpath)
        # initialize logging
        if getattr(self, 'realm', None):
            logger_name = "cdedb.frontend.{}".format(self.realm)
            logger_file = getattr(self.conf,
                                  "{}_FRONTEND_LOG".format(self.realm.upper()))
        else:
            logger_name = "cdedb.frontend"
            logger_file = self.conf.FRONTEND_LOG
        make_root_logger(
            logger_name, logger_file, self.conf.LOG_LEVEL,
            syslog_level=self.conf.SYSLOG_LEVEL,
            console_log_level=self.conf.CONSOLE_LOG_LEVEL)
        self.logger = logging.getLogger(logger_name)  # logger are thread-safe!
        self.logger.info("Instantiated {} with configpath {}.".format(
            self, configpath))
        self.decode_parameter = (
            lambda target, name, param:
            decode_parameter(secrets.URL_PARAMETER_SALT, target, name, param))

        def local_encode(target, name, param,
                         timeout=self.conf.PARAMETER_TIMEOUT):
            return encode_parameter(secrets.URL_PARAMETER_SALT, target, name,
                                    param, timeout=timeout)

        self.encode_parameter = local_encode

    def encode_notification(self, ntype, nmessage, nparams=None):
        """Wrapper around :py:meth:`encode_parameter` for notifications.

        The message format is A--B--C--D, with

        * A is the notification type, conforming to '[a-z]+'
        * B is the length of the notification message
        * C is the notification message
        * D is the parameter dict to be substituted in the message
          (json-encoded).

        :type ntype: str
        :type nmessage: str
        :type nparams: {str: object}
        :rtype: str
        """
        nparams = nparams or {}
        message = "{}--{}--{}--{}".format(ntype, len(nmessage), nmessage,
                                          json_serialize(nparams))
        return self.encode_parameter(
            '_/notification', 'displaynote', message,
            timeout=self.conf.UNCRITICAL_PARAMETER_TIMEOUT)

    def decode_notification(self, note):
        """Inverse wrapper to :py:meth:`encode_notification`.

        :type note: str
        :rtype: str, str, {str: object}
        """
        timeout, message = self.decode_parameter('_/notification',
                                                 'displaynote', note)
        if not message:
            return None, None, None
        parts = message.split("--")
        ntype = parts[0]
        length = int(parts[1])
        remainder = "--".join(parts[2:])
        nmessage = remainder[:length]
        nparams = json.loads(remainder[length + 2:])
        return ntype, nmessage, nparams

    def redirect(self, rs, target, params=None, anchor=None):
        """Create a response which diverts the user. Special care has to be
        taken not to lose any notifications.

        :type rs: :py:class:`RequestState`
        :type target: str
        :type params: {str: object}
        :type anchor: str or None
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
        if rs.errors and not rs.notifications:
            rs.notify("error", n_("Failed validation."))
        url = cdedburl(rs, target, params, force_external=True)
        if anchor is not None:
            url += "#" + anchor
        ret = basic_redirect(rs, url)
        if rs.notifications:
            notifications = [self.encode_notification(ntype, nmessage, nparams)
                             for ntype, nmessage, nparams in rs.notifications]
            ret.set_cookie("displaynote", json_serialize(notifications))
        return ret


def sanitize_None(data):
    """Helper to let jinja convert all ``None`` into empty strings for display
    purposes; thus we needn't be careful in this regard. (This is
    coherent with our policy that NULL and the empty string on SQL level
    shall have the same meaning).

    :type data: object
    :rtype: object
    """
    if data is None:
        return ""
    else:
        return data


def safe_filter(val):
    """Custom jinja filter to mark a string as safe.

    This prevents autoescaping of this entity. To be used for dynamically
    generated code we insert into the templates. It is basically equal to
    Jinja's builtin ``|safe``-Filter, but additionally takes care about None
    values.

    :type val: str
    :rtype: jinja2.Markup

    """
    if val is None:
        return None
    return jinja2.Markup(val)


def date_filter(val, formatstr="%Y-%m-%d", lang=None, verbosity="medium",
                passthrough=False):
    """Custom jinja filter to format ``datetime.date`` objects.

    :type val: datetime.date
    :type formatstr: str
    :param formatstr: Formatting used, if no l10n happens.
    :type lang: str or None
    :param lang: If not None, then localize to the passed language.
    :type verbosity: str
    :param verbosity: Controls localized formatting. Takes one of the
      following values: short, medium, long and full.
    :type passthrough: bool
    :param passthrough: If True return strings unmodified.
    :rtype: str
    """
    if val is None or val == '' or not isinstance(val, datetime.date):
        if passthrough and isinstance(val, str) and val:
            return val
        return None
    if lang:
        return babel.dates.format_date(val, locale=lang, format=verbosity)
    else:
        return val.strftime(formatstr)


def datetime_filter(val, formatstr="%Y-%m-%d %H:%M (%Z)", lang=None,
                    verbosity="medium", passthrough=False):
    """Custom jinja filter to format ``datetime.datetime`` objects.

    :type val: datetime.datetime
    :type formatstr: str
    :param formatstr: Formatting used, if no l10n happens.
    :type lang: str or None
    :param lang: If not None, then localize to the passed language.
    :type verbosity: str
    :param verbosity: Controls localized formatting. Takes one of the
      following values: short, medium, long and full.
    :type passthrough: bool
    :param passthrough: If True return strings unmodified.
    :rtype: str
    """
    if val is None or val == '' or not isinstance(val, datetime.datetime):
        if passthrough and isinstance(val, str) and val:
            return val
        return None
    if val.tzinfo is not None:
        val = val.astimezone(_BASICCONF.DEFAULT_TIMEZONE)
    else:
        _LOGGER.warning("Found naive datetime object {}.".format(val))
    if lang:
        return babel.dates.format_datetime(val, locale=lang, format=verbosity)
    else:
        return val.strftime(formatstr)


def money_filter(val, currency="EUR", lang="de"):
    """Custom jinja filter to format ``decimal.Decimal`` objects.

    This is for values representing monetary amounts.

    :type val: decimal.Decimal
    :type currency: str
    :type lang: str
    :rtype: str
    """
    if val is None:
        return None

    return babel.numbers.format_currency(val, currency, locale=lang)


def decimal_filter(val, lang="de"):
    """Cutom jinja filter to format floating point numbers.

    :type val: float
    :type lang: str
    :rtype: str
    """
    if val is None:
        return None

    return babel.numbers.format_decimal(val, locale=lang)


def cdedbid_filter(val):
    """Custom jinja filter to format persona ids with a check digit. Every user
    visible id should be formatted with this filter. The check digit is
    one of the letters between 'A' and 'K' to make a clear distinction
    between the numeric id and the check digit.

    :type val: int
    :rtype: str
    """
    if val is None:
        return None
    return "DB-{}-{}".format(val, compute_checkdigit(val))


def iban_filter(val):
    """
    Custom jinja filter for displaying IBANs in nice to read blocks.

    :type val: str or None
    :rtype: str or None
    """
    if val is None:
        return None
    else:
        val = val.strip().replace(" ", "")
        return " ".join(val[x:x + 4] for x in range(0, len(val), 4))


def escape_filter(val):
    """Custom jinja filter to reconcile escaping with the finalize method
    (which suppresses all ``None`` values and thus mustn't be converted to
    strings first).

    .. note:: Actually this returns a jinja specific 'safe string' which
      will remain safe when operated on. This means for example that the
      linebreaks filter has to make the string unsafe again, before it can
      work.

    :type val: object or None
    :rtype: str or None
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


def tex_escape_filter(val):
    """Custom jinja filter for escaping LaTeX-relevant charakters.

    :type val: object or None
    :rtype: str or None
    """
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

    def encode(self, o):
        # Override JSONEncoder.encode to avoid bypasses of interencode()
        # in original version
        chunks = self.iterencode(o, True)
        if self.ensure_ascii:
            return ''.join(chunks)
        else:
            return u''.join(chunks)

    def iterencode(self, o, _one_shot=False):
        chunks = super().iterencode(o, _one_shot)
        for chunk in chunks:
            chunk = chunk.replace('/', '\\x2f')
            chunk = chunk.replace('&', '\\x26')
            chunk = chunk.replace('<', '\\x3c')
            chunk = chunk.replace('>', '\\x3e')
            yield chunk


def json_filter(val):
    """Custom jinja filter to create json representation of objects. This is
    intended to allow embedding of values into generated javascript code.

    The result of this method does not need to be escaped -- more so if
    escaped, the javascript execution will probably fail.
    """
    return json.dumps(val, cls=CustomEscapingJSONEncoder)


def enum_filter(val, enum):
    """Custom jinja filter to convert enums to something printable.

    This exists mainly because of the possibility of None values.

    :type val: int
    :type enum: Enum
    :rtype: str
    """
    if val is None:
        return None
    return str(enum(val))


def genus_filter(val, female, male, unknown=None):
    """Custom jinja filter to select gendered form of a string.

    :type val: int
    :type female: str
    :type male: str
    :type unknown: str
    :rtype: str
    """
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


def stringIn_filter(val, alist):
    """Custom jinja filter to test if a value is in a list, but requiring
    equality only on string representation.

    This has to be an explicit filter becaus jinja does not support list
    comprehension.

    :type val: object
    :type alist: [object]
    :rtype: bool
    """
    return str(val) in (str(x) for x in alist)


def querytoparams_filter(val):
    """Custom jinja filter to convert query into a parameter dict
    which can be used to create a URL of the query.

    This could probably be done in jinja, but this would be pretty
    painful.

    :type val: :py:class:`cdedb.query.Query`
    :rtype: {str: object}
    """
    params = {}
    for field in val.fields_of_interest:
        params['qsel_{}'.format(field)] = True
    for field, op, value in val.constraints:
        params['qop_{}'.format(field)] = op.value
        if (isinstance(value, collections.Iterable)
                and not isinstance(value, str)):
            # TODO: Get separator from central place (also used in validation._
            # query_input)
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


def linebreaks_filter(val, replacement="<br>"):
    """Custom jinja filter to convert line breaks to <br>.

    This filter escapes the input value (if required), replaces the linebreaks
    and marks the output as safe html.

    :type val: str or jinja2.Markup
    :type replacement: jinja2.Markup
    :rtype: str
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


def get_bleach_cleaner():
    """Constructs bleach cleaner appropiate to untrusted user content.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    cleaner = getattr(BLEACH_CLEANER, 'cleaner', None)
    if cleaner:
        return cleaner
    TAGS = [
        'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li',
        'ol', 'strong', 'ul',
        # customizations
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'colgroup', 'col', 'tr', 'th',
        'thead', 'table', 'tbody', 'td', 'hr', 'p', 'span', 'div', 'pre', 'tt',
        'sup', 'sub', 'br', 'u', 'dl', 'dt', 'dd',]
    ATTRIBUTES = {
        'a': ['href', 'title'],
        'abbr': ['title'],
        'acronym': ['title'],
        # customizations
        '*': ['class'],
        'col': ['width'],
        'thead': ['valign'],
        'tbody': ['valign'],
        'table': ['border'],
        'th': ['colspan', 'rowspan'],
        'td': ['colspan', 'rowspan'],
        'div': ['id'],
        'h4': ['id'],
        'h5': ['id'],
        'h6': ['id'],
    }
    cleaner = bleach.sanitizer.Cleaner(tags=TAGS, attributes=ATTRIBUTES)
    BLEACH_CLEANER.cleaner = cleaner
    return cleaner


def bleach_filter(val):
    """Custom jinja filter to convert sanitize html with bleach.

    :type val: str
    :rtype: str
    """
    if val is None:
        return None
    return jinja2.Markup(get_bleach_cleaner().clean(val))


#: The Markdown parser has internal state, so we have to be a bit defensive
#: w.r.t. threads
MARKDOWN_PARSER = threading.local()


def md_id_wrapper(val, sep):
    """
    Wrap the markdown toc slugify function to attach an ID prefix.

    :param val: String to be made URL friendly.
    :type val: str
    :param sep: String to be used instead of Whitespace.
    :type sep: str
    :rtype: str
    """

    id_prefix = "CDEDB_MD_"

    return id_prefix + markdown.extensions.toc.slugify(val, sep)


def get_markdown_parser():
    """Constructs a markdown parser for general use.

    If you adjust this, please adjust the markdown specification in
    the docs as well."""
    md = getattr(MARKDOWN_PARSER, 'md', None)

    if md is None:
        md = markdown.Markdown(extensions=["extra", "sane_lists", "smarty", "toc"],
                               extension_configs={
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
                                           'right-double-quote': '&ldquo;'
                                       }
                                   }
                               })

        MARKDOWN_PARSER.md = md
    else:
        md.reset()
    return md


def md_filter(val):
    """Custom jinja filter to convert markdown to html.

    :type val: str
    :rtype: str
    """
    if val is None:
        return None
    md = get_markdown_parser()
    return bleach_filter(md.convert(val))


def xdictsort_filter(value, attribute, pad=False, reverse=False):
    """Allow sorting by an arbitrary attribute of the value.

    Jinja only provides sorting by key or entire value. Also Jinja does
    not allow comprehensions or lambdas, hence we have to use this.

    This obviously only works if the values allow access by key.

    :type value: {object: dict}
    :type attribute: str
    :param attribute: name of the attribute
    :type pad: bool
    :param pad: If True the attribute's value is interpreted as string and
      padded before sorting. The important use-case is numerical sorting.
    :type reverse: bool
    :param reverse: Sort in reversed order
    :rtype: [(object, dict)]
    """
    key = lambda item: item[1].get(attribute)
    if pad:
        if not value:
            return value
        to_str = lambda val: '' if val is None else str(val)
        max_len = max(len(to_str(v.get(attribute, ""))) for v in value.values())
        key = lambda item: to_str(item[1].get(attribute, None)).rjust(max_len,
                                                                      '\0')
    return sorted(value.items(), key=key, reverse=reverse)


def keydictsort_filter(value, sortkey, reverse=False):
    """

    :type value: {object: dict}
    :type sortkey: callable
    :type reverse: bool
    :rtype: [(object, dict)]
    """
    return sorted(value.items(), key=lambda e: sortkey(e[1]), reverse=reverse)


def enum_entries_filter(enum, processing=None, raw=False):
    """
    Transform an Enum into a list of of (value, string) tuple entries. The
    string is piped trough the passed processing callback function to get the
    human readable and translated caption of the value.

    :type enum: enum.Enum
    :type processing: callable object -> str
    :param processing: A function to be applied on the value's string
        representation before adding it to the result tuple. Typically this is
        gettext()
    :type raw: bool
    :param raw: If this is True, the enum entries are passed to processing as
        is, otherwise they are converted to str first.
    :rtype: [(object, object)]
    :return: A list of tuples to be used in the input_checkboxes or
        input_select macros.
    """
    if processing is None:
        processing = lambda x: x
    if raw:
        pre = lambda x: x
    else:
        pre = str
    return sorted((entry.value, processing(pre(entry))) for entry in enum)


def dict_entries_filter(items, *args):
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of specified fields of the value dict.

    Example::

        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> dict_entries_filter(items, 'name', 'active')
        [('a', True), ('b', False)]

    :type items: [(object, dict)]
    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :type args: [object] or None
    :param args: Additional positional arguments describing which keys of
      the dicts should be inserted in the resulting tuple
    :rtype: [[object]]
    :return: A list of tuples (e.g. to be used in the input_checkboxes or
      input_select macros), built from the selected fields of the dicts
    """
    return [tuple(value[k] for k in args) for key, value in items]


def xdict_entries_filter(items, *args, include=None):
    """
    Transform a list of dict items with dict-type values into a list of
    tuples of strings with specified format. Each entry of the resulting
    tuples is built by applying the item's value dict to a format string.

    Example::
        >>> items = [(1, {'id': 1, 'name': 'a', 'active': True}),
                     (2, {'id': 2, 'name': 'b', 'active': False})]
        >>> xdict_entries_filter(items, '{id}', '{name} -- {active}')
        [('1', 'a -- True'), ('2', 'b -- False')]

    :type items: [(object, dict)]
    :param items: A list of 2-element tuples. The first element of each
      tuple is ignored, the second must be a dict
    :type args: [str]
    :param args: Additional positional arguments, which are format strings
      for the resulting tuples. They can use named format specifications to
      access the dicts' fields.
    :type include: [str] or None
    :param include: An iteratable to search for items' keys. Only items with
      their key being in `include` are included in the results list
    :rtype: [[str]]
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
    'escape': escape_filter,
    'e': escape_filter,
    'json': json_filter,
    'stringIn': stringIn_filter,
    'querytoparams': querytoparams_filter,
    'genus': genus_filter,
    'linebreaks': linebreaks_filter,
    'md': md_filter,
    'enum': enum_filter,
    'xdictsort': xdictsort_filter,
    's': safe_filter,
    'tex_escape': tex_escape_filter,
    'te': tex_escape_filter,
    'enum_entries': enum_entries_filter,
    'dict_entries': dict_entries_filter,
    'xdict_entries': xdict_entries_filter,
    'keydictsort': keydictsort_filter,
}


class AbstractFrontend(BaseApp, metaclass=abc.ABCMeta):
    """Common base class for all frontends."""
    #: to be overridden by children
    realm = None
    #: to be overridden by children
    used_shards = []

    def __init__(self, configpath, *args, **kwargs):
        """
        :type configpath: str
        """
        super().__init__(configpath, *args, **kwargs)
        # TODO With buster we can activate the trimming of the trans env
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(self.conf.REPOSITORY_PATH / "cdedb/frontend/templates")),
            extensions=('jinja2.ext.with_', 'jinja2.ext.i18n', 'jinja2.ext.do',
                        'jinja2.ext.loopcontrols', 'jinja2.ext.autoescape'),
            finalize=sanitize_None, autoescape=True,
            auto_reload=self.conf.CDEDB_DEV)
        self.jinja_env.filters.update(JINJA_FILTERS)
        self.jinja_env.globals.update({
            'now': now,
            'query_mod': query_mod,
            'glue': glue,
            'enums': ENUMS_DICT,
            'encode_parameter': self.encode_parameter,
            'staticurl': functools.partial(staticurl,
                                           version=self.conf.GIT_COMMIT[:8]),
            'docurl': docurl,
            'CDEDB_OFFLINE_DEPLOYMENT': self.conf.CDEDB_OFFLINE_DEPLOYMENT,
            'CDEDB_DEV': self.conf.CDEDB_DEV,
            'ANTI_CSRF_TOKEN_NAME': ANTI_CSRF_TOKEN_NAME,
            'GIT_COMMIT': self.conf.GIT_COMMIT,
            'I18N_LANGUAGES': self.conf.I18N_LANGUAGES,
            'EntitySorter': EntitySorter,
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
        )
        self.shards = [shardcls(self) for shardcls in self.used_shards]
        for shard in self.shards:
            self.republish(shard)

    @abc.abstractmethod
    def finalize_session(self, rs, connpool, auxilliary=False):
        """Allow realm specific tweaking of the session.

        This is intended to add orga and moderator infos in the event
        and ml realm respectively.

        This will be called by
        :py:class:`cdedb.frontend.application.Application` and is thus
        part of the interface.

        :type rs: :py:class:`RequestState`
        :type auxilliary: bool
        :param auxilliary: If True this is only called to make realm specific
          functionality available, but the actual endpoint will not lie in
          this realm.
        :rtype: None
        """
        return

    def _republish(self, shard, name, method):
        """Uninlined code from republish() to avoid late binding."""
        @functools.wraps(method)
        def new_meth(obj, rs, *args, **kwargs):
            method(rs, *args, **kwargs)
        for attr in ('access_list', 'modi', 'check_anti_csrf', 'cron'):
            if hasattr(method, attr):
                setattr(new_meth, attr, getattr(method, attr))
        # Keep a copy of the originating shard, so we
        # introspect the source of each published method
        new_meth.origin = shard
        setattr(self, name, types.MethodType(new_meth, self))

    def republish(self, shard):
        """Republish the functionality of a frontend shard.

        This way any user of the frontend can be unaware of the
        internal split into shards.

        :type shard: AbstractFrontendShard
        """
        for name, method in inspect.getmembers(shard, inspect.ismethod):
            if hasattr(method, 'access_list') or hasattr(method, 'cron'):
                if hasattr(self, name):
                    raise RuntimeError("Method already exists", name)
                self._republish(shard, name, method)

    @classmethod
    @abc.abstractmethod
    def is_admin(cls, rs):
        """Since each realm may have its own application level roles, it may
        also have additional roles with elevated privileges.

        :type rs: :py:class:`RequestState`
        :rtype: bool
        """
        return "{}_admin".format(cls.realm) in rs.user.roles

    def fill_template(self, rs, modus, templatename, params):
        """Central function for generating output from a template. This
        makes several values always accessible to all templates.

        .. note:: We change the templating syntax for TeX templates since
                  jinjas default syntax is nasty for this.

        :type rs: :py:class:`RequestState`
        :type modus: str
        :param modus: Type of thing we want to generate; can be one of
          * web,
          * mail,
          * tex.
        :type templatename: str
        :param templatename: file name of template without extension
        :type params: {str: object}
        :rtype: str
        """

        def _cdedblink(endpoint, params=None, magic_placeholders=None):
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

        def _show_user_link(persona_id, quote_me=None, event_id=None,
                            ml_id=None):
            """Convenience method to create link to user data page.

            This is lengthy otherwise because of the parameter encoding
            and a pretty frequent operation so that it is beneficial to
            have this helper.

            :type persona_id: int
            :type quote_me: bool or None
            :type event_id: int
            :type ml_id: int
            :rtype: str
            """
            params = {
                'persona_id': persona_id,
                'confirm_id': self.encode_parameter(
                    "core/show_user", "confirm_id", persona_id, timeout=None)}
            if quote_me:
                params['quote_me'] = True
            if event_id:
                params['event_id'] = event_id
            if ml_id:
                params['ml_id'] = ml_id
            return cdedburl(rs, 'core/show_user', params)

        errorsdict = {}
        for key, value in rs.errors:
            errorsdict.setdefault(key, []).append(value)
        # here come the always accessible things promised above

        data = {
            'ambience': rs.ambience,
            'cdedblink': _cdedblink,
            'errors': errorsdict,
            'generation_time': lambda: (now() - rs.begin),
            'gettext': rs.gettext,
            'is_admin': self.is_admin(rs),
            'lang': rs.lang,
            'ngettext': rs.ngettext,
            'notifications': rs.notifications,
            'original_request': rs.request,
            'show_user_link': _show_user_link,
            'user': rs.user,
            'values': rs.values,
        }
        # check that default values are not overridden
        assert (not set(data) & set(params))
        merge_dicts(data, params)
        if modus == "tex":
            jinja_env = self.jinja_env_tex
        elif modus == "mail":
            jinja_env = self.jinja_env_mail
        else:
            jinja_env = self.jinja_env
        t = jinja_env.get_template(str(pathlib.Path(
            modus, self.realm, "{}.tmpl".format(templatename))))
        return t.render(**data)

    @staticmethod
    def send_csv_file(rs, mimetype='text/csv', filename=None, inline=True, *,
                      path=None, afile=None, data=None):
        """Wrapper around :py:meth:`send_file` for CSV files.

        This makes Excel happy by adding a BOM at the beginning of the
        file. All parameters (except for encoding) are as in the wrapped
        method.
        """
        return AbstractFrontend.send_file(
            rs, mimetype=mimetype, filename=filename, inline=inline, path=path,
            afile=afile, data=data, encoding='utf-8-sig')

    @staticmethod
    def send_file(rs, mimetype=None, filename=None, inline=True, *,
                  path=None, afile=None, data=None, encoding='utf-8'):
        """Wrapper around :py:meth:`werkzeug.wsgi.wrap_file` to offer a file for
        download.

        Exactly one of the inputs has to be provided.

        :type rs: :py:class:`RequestState`
        :type mimetype: str or None
        :param mimetype: If not None the mime type of the file to be sent.
        :type filename: str or None
        :param filename: If not None the default file name used if the user
          tries to save the file to disk
        :type inline: bool
        :param inline: Set content disposition to force display in browser (if
          True) or to force a download box (if False).
        :type path: str or pathlib.Path
        :type afile: file like
        :param afile: should be opened in binary mode
        :type data: str or bytes
        :param encoding: The character encoding to be uses, if `data` is given
          as str
        :type encoding: str
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        if not path and not afile and not data:
            raise ValueError(n_("No input specified."))
        if (path and afile) or (path and data) or (afile and data):
            raise ValueError(n_("Ambiguous input."))
        if path and not pathlib.Path(path).is_file():
            raise werkzeug.exceptions.NotFound()
        if path:
            # TODO Can we use a with context here or maybe close explicitly?
            afile = open(str(path), 'rb')
        elif data is not None:
            afile = io.BytesIO()
            if isinstance(data, str):
                afile.write(data.encode(encoding))
            else:
                afile.write(data)
            afile.seek(0)
        f = werkzeug.wsgi.wrap_file(rs.request.environ, afile)
        extra_args = {}
        if mimetype is not None:
            extra_args['mimetype'] = mimetype
        headers = []
        disposition = "inline" if inline else "attachment"
        if filename is not None:
            disposition += '; filename="{}"'.format(filename)
        headers.append(('Content-Disposition', disposition))
        headers.append(('X-Generation-Time', str(now() - rs.begin)))
        return Response(f, direct_passthrough=True, headers=headers,
                        **extra_args)

    @staticmethod
    def send_json(rs, data):
        """Slim helper to create json responses.

        :type rs: :py:class:`RequestState`
        :type data: object
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        rs.response = Response(json_serialize(data),
                               mimetype='application/json')
        rs.response.headers.add('X-Generation-Time', str(now() - rs.begin))
        return rs.response

    def render(self, rs, templatename, params=None):
        """Wrapper around :py:meth:`fill_template` specialised to generating
        HTML responses.

        :type rs: :py:class:`RequestState`
        :type templatename: str
        :type params: {str: object}
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        params = params or {}
        # handy, should probably survive in a commented HTML portion
        if 'debugstring' not in params and self.conf.CDEDB_DEV:
            debugstring = glue(
                "We have is_multithreaded={}; is_multiprocess={};",
                "base_url={} ; cookies={} ; url={} ; is_secure={} ;",
                "method={} ; remote_addr={} ; values={}, ambience={},",
                "errors={}, time={}").format(
                rs.request.is_multithread, rs.request.is_multiprocess,
                rs.request.base_url, rs.request.cookies, rs.request.url,
                rs.request.is_secure, rs.request.method,
                rs.request.remote_addr, rs.values, rs.ambience, rs.errors,
                now())
            params['debugstring'] = debugstring
        if rs.errors and not rs.notifications:
            rs.notify("error", n_("Failed validation."))
        if self.conf.LOCKDOWN:
            rs.notify("info", n_("The database currently undergoes "
                                 "maintenance and is unavailable."))
        # A nonce to mark safe <script> tags in context of the CSP header
        csp_nonce = secure_token_hex(12)
        params['csp_nonce'] = csp_nonce

        html = self.fill_template(rs, "web", templatename, params)
        rs.response = Response(html, mimetype='text/html')
        rs.response.headers.add('X-Generation-Time', str(now() - rs.begin))

        # Add CSP header to disallow scripts, styles, images and objects from
        # other domains. This is part of XSS mitigation
        csp_header_template = glue(
            "default-src 'self';",
            "script-src 'unsafe-inline' 'self' https: 'nonce-{}';",
            "style-src 'self' 'unsafe-inline';",
            "img-src *")
        rs.response.headers.add('Content-Security-Policy',
                                csp_header_template.format(csp_nonce))
        return rs.response

    def do_mail(self, rs, templatename, headers, params=None, attachments=None):
        """Wrapper around :py:meth:`fill_template` specialised to sending
        emails. This does generate the email and send it too.

        Some words about email trouble. Bounced mails go by default to a
        special address ``bounces@cde-ev.de``, which will be a list not
        managed via the DB. For mailinglists the return path will be a
        list specific bounce address which delivers the bounces to the
        moderators.

        :type rs: :py:class:`RequestState`
        :type templatename: str
        :type headers: {str: str}
        :param headers: mandatory headers to supply are To and Subject
        :type params: {str: object}
        :type attachments: [{str: object}] or None
        :param attachments: Each dict describes one attachment. The possible
          keys are path (a ``str``), file (a file like), mimetype (a ``str``),
          filename (a ``str``).
        :rtype: str or None
        :returns: see :py:meth:`_send_mail` for details, we automatically
          store the path in ``rs``
        """
        params = params or {}
        params['headers'] = headers
        text = self.fill_template(rs, "mail", templatename, params)
        # do i18n here, so _create_mail needs to know less context
        headers['Subject'] = headers['Subject']
        msg = self._create_mail(text, headers, attachments)
        ret = self._send_mail(msg)
        if ret:
            # This is mostly intended for the test suite.
            rs.notify("info", n_("Stored email to hard drive at %(path)s"),
                      {'path': ret})
        return ret

    def _create_mail(self, text, headers, attachments):
        """Helper for actual email instantiation from a raw message.

        :type text: str
        :type headers: {str: str}
        :type attachments: [{str: object}] or None
        :rtype: :py:class:`email.message.Message`
        """
        defaults = {"From": self.conf.DEFAULT_SENDER,
                    "Reply-To": self.conf.DEFAULT_REPLY_TO,
                    "Return-Path": self.conf.DEFAULT_RETURN_PATH,
                    "Cc": tuple(),
                    "Bcc": tuple(),
                    "domain": self.conf.MAIL_DOMAIN,
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
        payload = msg.get_payload()
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
            msg = container
        for header in ("To", "Cc", "Bcc"):
            nonempty = {x for x in headers[header] if x}
            if nonempty != set(headers[header]):
                self.logger.warning("Empty values zapped in email recipients.")
            if headers[header]:
                msg[header] = ", ".join(nonempty)
        for header in ("From", "Reply-To", "Subject", "Return-Path"):
            msg[header] = headers[header]
        msg["Message-ID"] = email.utils.make_msgid(domain=self.conf.MAIL_DOMAIN)
        msg["Date"] = email.utils.format_datetime(now())
        return msg

    @staticmethod
    def _create_attachment(attachment):
        """Helper instantiating an attachment via the email module.

        :type attachment: {str: object}
        :param attachment: see :py:meth:`do_mail` for a description of keys
        :rtype: :py:class:`email.message.Message`
        """
        mimetype = attachment.get('mimetype') or 'application/octet-stream'
        maintype, subtype = mimetype.split('/', 1)
        if attachment.get('file'):
            afile = attachment['file']
        else:
            # TODO use a with context?
            if maintype == "text":
                afile = open(attachment['path'])
            else:
                afile = open(str(attachment['path']), 'rb')
        # Only support common types
        factories = {
            'application': email.mime.application.MIMEApplication,
            'audio': email.mime.audio.MIMEAudio,
            'image': email.mime.image.MIMEImage,
            'text': email.mime.text.MIMEText,
        }
        ret = factories[maintype](afile.read(), _subtype=subtype)
        if not attachment.get('file'):
            afile.close()
        if attachment.get('filename'):
            ret.add_header('Content-Disposition', 'attachment',
                           filename=attachment['filename'])
        return ret

    def _send_mail(self, msg):
        """Helper for getting an email onto the wire.

        :type msg: :py:class:`email.message.Message`
        :rtype: str or None
        :returns: Name of the file the email was saved in -- however this
          happens only in development mode. This is intended for consumption
          by the test suite.
        """
        ret = None
        if not msg["To"] and not msg["Cc"] and not msg["Bcc"]:
            self.logger.warning("No recipients for mail. Dropping it.")
            return None
        if not self.conf.CDEDB_DEV:
            s = smtplib.SMTP(self.conf.MAIL_HOST)
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

    def redirect_show_user(self, rs, persona_id, quote_me=None):
        """Convenience function to redirect to a user detail page.

        The point is, that encoding the ``confirm_id`` parameter is
        somewhat lengthy and only necessary because of our paranoia.

        :type rs: :py:class:`RequestState`
        :type quote_me: bool or None
        :type persona_id: int
        :rtype: :py:class:`werkzeug.wrappers.Response`
        """
        cid = self.encode_parameter(
            "core/show_user", "confirm_id", persona_id, timeout=None)
        params = {'confirm_id': cid, 'persona_id': persona_id}
        if quote_me is not None:
            params['quote_me'] = True
        return self.redirect(rs, 'core/show_user', params=params)

    @staticmethod
    def notify_return_code(rs, code, success=n_("Change committed."),
                           pending=n_("Change pending."),
                           error=n_("Change failed.")):
        """Small helper to issue a notification based on a return code.

        We allow some flexibility in what type of return code we accept. It
        may be a boolean (with the obvious meanings), an integer (specifying
        the number of changed entries, and negative numbers for entries with
        pending review) or None (signalling failure to acquire something).

        :type rs: :py:class:`RequestState`
        :type success: str
        :type code: int or bool or None
        :param success: Affirmative message for positive return codes.
        :param pending: Message for negative return codes signalling review.
        :param error: Exception message for zero return codes.
        """
        if not code:
            rs.notify("error", error)
        elif code is True or code > 0:
            rs.notify("success", success)
        elif code < 0:
            rs.notify("info", pending)
        else:
            raise RuntimeError(n_("Impossible."))

    def safe_compile(self, rs, target_file, cwd, runs, errormsg):
        """Helper to compile latex documents in a safe way.

        This catches exepctions during compilation and displays a more helpful
        error message instead.

        :type rs: :py:class:`RequestState`
        :type target_file: str
        :param target_file: name of the file to compile.
        :type cwd: :py:class:`pathlib.Path`
        :param cwd: Path of the target file.
        :param runs: number of times LaTeX is run (for references etc.)
        :type errormsg: str or None
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :rtype: :py:class:`pathlib.Path`
        :returns: Path to the compiled pdf.
        """
        if target_file.endswith('.tex'):
            pdf_file = "{}.pdf".format(target_file[:-4])
        else:
            pdf_file = "{}.pdf".format(target_file)
        pdf_path = pathlib.Path(cwd, pdf_file)

        args = ("pdflatex", "-interaction", "batchmode", target_file)
        self.logger.info("Invoking {}".format(args))
        try:
            for _ in range(runs):
                subprocess.check_call(args, stdout=subprocess.DEVNULL, cwd=cwd)
        except subprocess.CalledProcessError as e:
            if pdf_path.exists():
                self.logger.debug("Deleting corrupted file {}".format(pdf_path))
                pdf_path.unlink()
            self.logger.debug("Exception \"{}\" caught and handled.".format(e))
            errormsg = errormsg or n_(
                "LaTeX compilation failed. Try downloading the "
                "source files and compiling them manually.")
            rs.notify("error", errormsg)
        return pdf_path

    def latex_compile(self, rs, data, runs=2, errormsg=None):
        """Run LaTeX on the provided document.

        This takes care of the necessary temporary files.

        :type rs: :py:class:`RequestState`
        :type data: str
        :type runs: int
        :param runs: number of times LaTeX is run (for references etc.)
        :type errormsg: str or None
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :rtype: bytes
        :returns: the compiled document as blob
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            with tempfile.NamedTemporaryFile(dir=tmp_dir) as tmp_file:
                tmp_file.write(data.encode('utf8'))
                tmp_file.flush()
                path = self.safe_compile(
                    rs, tmp_file.name, tmp_dir, runs=runs, errormsg=errormsg)
                if path.exists():
                    with open(path, 'rb') as pdf:
                        return pdf.read()
                else:
                    return None

    def serve_latex_document(self, rs, data, filename, runs=2, errormsg=None):
        """Generate a response from a LaTeX document.

        This takes care of the necessary temporary files.

        :type rs: :py:class:`RequestState`
        :type data: str
        :param data: the LaTeX document
        :type filename: str
        :param filename: name to serve the document as, without extension
        :type runs: int
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled pdf.
        :type errormsg: str or None
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :rtype: werkzeug.Response
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

    def serve_complex_latex_document(self, rs, tmp_dir, work_dir_name,
                                     tex_file_name, runs=2, errormsg=None):
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

        :type rs: :py:class:`RequestState`
        :type tmp_dir: str or pathlib.Path
        :param tmp_dir: path of temporary directory
        :type work_dir_name: str
        :param work_dir_name: name of working directory inside temporary
          directory.
        :type tex_file_name: str
        :param tex_file_name: name of the tex file (including extension),
          this will be used to derived the name to use when serving the
          compiled pdf file.
        :type runs: int
        :param runs: Number of times LaTeX is run (for references etc.). If this
          is zero, we serve the source tex file, instead of the compiled
          pdf. More specifically we serve a gzipped tar archive containing
          the working directory.
        :type errormsg: str or None
        :param errormsg: Error message to display when compilation fails.
            Defaults to error message for event downloads.
        :rtype: werkzeug.Response
        """
        if not runs:
            target = pathlib.Path(
                tmp_dir, "{}.tar.gz".format(work_dir_name))
            args = ("tar", "-vczf", str(target), work_dir_name)
            self.logger.info("Invoking {}".format(args))
            subprocess.check_call(args, stdout=subprocess.DEVNULL,
                                  cwd=str(tmp_dir))
            if tex_file_name.endswith('.tex'):
                tex_file = "{}.tar.gz".format(tex_file_name[:-4])
            else:
                tex_file = "{}.tar.gz".format(tex_file_name)
            return self.send_file(
                rs, path=target, inline=False,
                filename=tex_file)
        else:
            work_dir = pathlib.Path(tmp_dir, work_dir_name)
            if tex_file_name.endswith('.tex'):
                pdf_file = "{}.pdf".format(tex_file_name[:-4])
            else:
                pdf_file = "{}.pdf".format(tex_file_name)
            path = self.safe_compile(
                rs, tex_file_name, cwd=str(work_dir), runs=runs,
                errormsg=errormsg)
            if path.exists():
                return self.send_file(
                    rs, mimetype="application/pdf",
                    path=(work_dir / pdf_file),
                    filename=pdf_file)
            else:
                return None


class AbstractFrontendShard(metaclass=abc.ABCMeta):
    """Common base class for all frontend shards.

    These are used to split mostly independent functionality from a
    frontend into a separate unit.

    The frontend is then responsible to make the functionality of the
    shard accessible to its users without leaking the implementation
    details. For this purpose the method
    `AbstractFrontend.republish()` is used.
    """
    def __init__(self, parent, *args, **kwargs):
        """
        :type parent: AbstractFrontend
        """
        super().__init__(*args, **kwargs)
        self.parent = parent


class Worker(threading.Thread):
    """Customization wrapper around ``threading.Thread``.

    This takes care of initializing a new (basically cloned) request
    state object, containing a separate database connection, so that
    concurrency is no concern.
    """

    def __init__(self, conf, task, rs, *args, **kwargs):
        """
        :type confpath: :py:class:`cdedb.Config`
        :type realm: str
        :type task: callable
        :param task: Will be called with exactly one argument (the cloned
          request state) until it returns something falsy.
        :type rs: :py:class:`RequestState`
        """
        rrs = RequestState(
            rs.sessionkey, rs.user, rs.request, None, [], rs.urls,
            rs.requestargs, [], copy.deepcopy(rs.values),
            rs.lang, rs.gettext, rs.ngettext, rs._coders, rs.begin,
            rs.scriptkey)
        secrets = SecretsConfig(conf._configpath)
        connpool = connection_pool_factory(
            conf.CDB_DATABASE_NAME, DATABASE_ROLES, secrets, conf.DB_PORT)
        rrs._conn = connpool[roles_to_db_role(rs.user.roles)]

        def runner():
            """Implements the actual loop running the task inside the Thread."""
            while task(rrs):
                pass

        super().__init__(target=runner, daemon=False, *args, **kwargs)


def reconnoitre_ambience(obj, rs):
    """Provide automatic lookup of objects in a standard way.

    This creates an ambience dict providing objects for all ids passed
    as part of the URL path. The naming is not predetermined, but as a
    convention the object name should be the parameter named minus the
    '_id' suffix.

    :type obj: :py:class:`AbstractFrontend`
    :type rs: :py:class:`RequestState`
    :rtype: {str: object}
    """
    Scout = collections.namedtuple('Scout', ('getter', 'param_name',
                                             'object_name', 'dependencies'))
    t = tuple()

    def do_assert(x):
        if not x:
            raise werkzeug.exceptions.BadRequest(
                rs.gettext("Inconsistent request."))

    def attachment_check(a):
        if a['attachment']['ballot_id']:
            return a['attachment']['ballot_id'] == rs.requestargs['ballot_id']
        else:
            return (a['attachment']['assembly_id']
                    == rs.requestargs['assembly_id'])

    scouts = (
        Scout(lambda anid: obj.coreproxy.get_persona(rs, anid), 'persona_id',
              'persona', t),
        # no case_id for genesis cases since they are special and cause
        # PrivilegeErrors
        Scout(lambda anid: obj.cdeproxy.get_lastschrift(rs, anid),
              'lastschrift_id', 'lastschrift', t),
        Scout(lambda anid: obj.cdeproxy.get_lastschrift_transaction(rs, anid),
              'transaction_id', 'transaction',
              ((lambda a: do_assert(a['transaction']['lastschrift_id']
                                    == a['lastschrift']['id'])),)),
        Scout(lambda anid: obj.pasteventproxy.get_institution(rs, anid),
              'institution_id', 'institution', t),
        Scout(lambda anid: obj.eventproxy.get_event(rs, anid),
              'event_id', 'event', t),
        Scout(lambda anid: obj.pasteventproxy.get_past_event(rs, anid),
              'pevent_id', 'pevent', t),
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
              'assembly_id', 'assembly', t),
        Scout(lambda anid: obj.assemblyproxy.get_ballot(rs, anid),
              'ballot_id', 'ballot',
              ((lambda a: do_assert(a['ballot']['assembly_id']
                                    == a['assembly']['id'])),)),
        Scout(None, 'candidate_id', None,
              ((lambda a: do_assert(rs.requestargs['candidate_id']
                                    in a['ballot']['candidates'])),)),
        Scout(lambda anid: obj.mlproxy.get_mailinglist(rs, anid),
              'mailinglist_id', 'mailinglist', t),
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


def access(*roles, modi=None, check_anti_csrf=None):
    """The @access decorator marks a function of a frontend for publication and
    adds initialization code around each call.

    :type roles: [str]
    :param roles: privilege required (any of the passed)
    :type modi: {str}
    :param modi: HTTP methods allowed for this invocation
    :type check_anti_csrf: bool or None
    :param check_anti_csrf: Control if the anti csrf check should be enabled
        on this endpoint. If not specified, it will be enabled, if "POST" is in
        the allowed methods.
    """
    modi = modi or {"GET", "HEAD"}
    access_list = set(roles)

    def decorator(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if rs.user.roles & access_list:
                rs.ambience = reconnoitre_ambience(obj, rs)
                return fun(obj, rs, *args, **kwargs)
            else:
                if rs.user.roles == {"anonymous"}:
                    params = {
                        'wants': rs._coders['encode_parameter'](
                            "core/index", "wants", rs.request.url,
                            timeout=None),
                    }
                    ret = basic_redirect(rs, cdedburl(rs, "core/index", params))
                    notifications = json_serialize([
                        rs._coders['encode_notification'](
                            "error", n_("You must login."))])
                    ret.set_cookie("displaynote", notifications)
                    return ret
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("Access denied to {realm}/{endpoint}.").format(
                        realm=obj.__class__.__name__, endpoint=fun.__name__))

        new_fun.access_list = access_list
        new_fun.modi = modi
        new_fun.check_anti_csrf =\
            (check_anti_csrf
             if check_anti_csrf is not None
             else not modi <= {'GET', 'HEAD'} and "anonymous" not in roles)
        return new_fun

    return decorator


def periodic(name, period=1):
    """This decorator marks a function of a frontend for periodic execution.

    This just adds a flag and all of the actual work is done by the
    CronFrontend.

    :type name: str
    :param name: the name of this job
    :type period: int
    :param period: the interval in which to execute this job (e.g. period ==
      2 means every second invocation of the CronFrontend)
    """
    def decorator(fun):
        fun.cron = {
            'name': name,
            'period': period,
        }
        return fun

    return decorator


def cdedburl(rs, endpoint, params=None, force_external=False,
             magic_placeholders=None):
    """Construct an HTTP URL.

    :type rs: :py:class:`RequestState`
    :type endpoint: str
    :param endpoint: as defined in :py:data:`cdedb.frontend.paths.CDEDB_PATHS`
    :type params: {str: object}
    :type force_external: bool
    :type magic_placeholders: [str]
    :param magic_placeholders: These are parameter names which behave as if
      the following code would be executed::

          for i, name in enumerate(magic_placeholders):
              params[name] = "_CDEDB_MAGIC_URL_PLACEHOLDER_{}_".format(i)

      The use case is that we want to generate string templates of URLs for
      consumption by Javascript code with the possibility of inserting some
      parameters at execution time.
    :rtype: str
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
    allparams = werkzeug.datastructures.MultiDict()
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


def staticurl(path, version=None):
    """Construct an HTTP URL to a static resource (to be found in the static
    directory). We encapsulate this here so moving the directory around
    causes no pain.

    :type path: str
    :param version: If not None, this string is appended to the URL as an URL
        parameter. This can be used to force Browsers to flush their caches on
        code updates.
    :type version: str
    :rtype: str
    """
    return str(pathlib.Path("/static", path)) \
        + ('?v=' + version if version else '')


def docurl(topic, anchor=None):
    """Construct an HTTP URL to a doc page.

    :type topic: str
    :type anchor: str or None
    :rtype: str
    """
    ret = str(pathlib.Path("/doc", topic + ".html"))
    if anchor:
        ret = ret + "#" + anchor
    return ret


def REQUESTdata(*spec):
    """Decorator to extract parameters from requests and validate them. This
    should always be used, so automatic form filling works as expected.

    This strips surrounding whitespace. If this is undesired at some
    point in the future we have to add an override here.

    :type spec: [(str, str)]
    :param spec: Specification of parameters to extract. The
      first value of a tuple is the name of the parameter to look out
      for. The second value of each tuple denotes the sort of parameter to
      extract, valid values are all validators from
      :py:mod:`cdedb.validation` vanilla, enclosed in square brackets or
      with a leading hash, the square brackets are for HTML elements which
      submit multiple values for the same parameter (e.g. <select>) which
      are extracted as lists and the hash signals an encoded parameter,
      which needs to be decoded first.
    """

    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            for name, argtype in spec:
                if name not in kwargs:
                    if argtype.startswith('[') and argtype.endswith(']'):
                        vals = tuple(val.strip()
                                     for val in rs.request.values.getlist(name))
                        if vals:
                            rs.values.setlist(name, vals)
                        else:
                            # We have to be careful, since empty lists are
                            # problematic for the werkzeug MultiDict
                            rs.values[name] = None
                        kwargs[name] = tuple(
                            check_validation(rs, argtype[1:-1], val, name)
                            for val in vals)
                    else:
                        val = rs.request.values.get(name, "").strip()
                        rs.values[name] = val
                        if argtype.startswith('#'):
                            argtype = argtype[1:]
                            if val:
                                # only decode if exists
                                timeout, val = rs._coders['decode_parameter'](
                                    "{}/{}".format(obj.realm, fun.__name__),
                                    name, val)
                                if timeout is True:
                                    rs.notify("warning", n_("Link expired."))
                                if timeout is False:
                                    rs.notify("warning", n_("Link invalid."))
                                if val is None:
                                    # Clean out the invalid value
                                    rs.values[name] = None
                        kwargs[name] = check_validation(rs, argtype, val, name)
            return fun(obj, rs, *args, **kwargs)

        return new_fun

    return wrap


def REQUESTdatadict(*proto_spec):
    """Similar to :py:meth:`REQUESTdata`, but doesn't hand down the
    parameters as keyword-arguments, instead packs them all into a dict and
    passes this as ``data`` parameter. This does not do validation since
    this is infeasible in practice.

    This strips surrounding whitespace. If this is undesired at some
    point in the future we have to add an override here.

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

    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            data = {}
            for name, argtype in spec:
                if argtype == "str":
                    data[name] = rs.request.values.get(name, "").strip()
                elif argtype == "[str]":
                    data[name] = tuple(
                        val.strip() for val in rs.request.values.getlist(name))
                else:
                    raise ValueError(n_("Invalid argtype {t} found.").format(
                        t=argtype))
                rs.values[name] = data[name]
            return fun(obj, rs, *args, data=data, **kwargs)

        return new_fun

    return wrap


def request_extractor(rs, args, constraints=None):
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

    :type rs: :py:class:`RequestState`
    :type args: [(str, str)]
    :param args: handed through to the decorator
    :type constraints: [(callable, (str, exception))]
    :param constraints: additional constraints that shoud produce
      validation errors
    :rtype: {str: object}
    :returns: dict containing the requested values

    """
    @REQUESTdata(*args)
    def fun(_, rs, **kwargs):
        if not rs.errors:
            for checker, error in constraints or []:
                if not checker(kwargs):
                    rs.errors.append(error)
        return kwargs

    return fun(None, rs)


def request_dict_extractor(rs, args):
    """Utility to apply REQUESTdatadict later than usual.

    Like :py:meth:`request_extractor`.

    :type rs: :py:class:`RequestState`
    :type args: [str]
    :param args: handed through to the decorator
    :rtype: {str: object}
    :returns: dict containing the requested values
    """

    @REQUESTdatadict(*args)
    def fun(_, rs, data):
        return data

    # This looks wrong. but is correct.
    return fun(None, rs)


def REQUESTfile(*args):
    """Decorator to extract file uploads from requests.

    :type args: [str]
    :param args: Names of file parameters.
    """

    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args2, **kwargs):
            for name in args:
                if name not in kwargs:
                    kwargs[name] = rs.request.files.get(name, None)
                rs.values[name] = kwargs[name]
            return fun(obj, rs, *args2, **kwargs)

        return new_fun

    return wrap


def event_usage(fun):
    """Indicate usage of the event realm.

    This is intended as decorator to signal a call into the event
    backend from a non-event frontend. The effect is to make the orga
    information available which is normally only supplied if requesting
    an endpoint in the event realm.

    :type fun: callable
    :rtype: callable
    """
    if hasattr(fun, 'realm_usage'):
        fun.realm_usage.add('event')
    else:
        fun.realm_usage = {'event'}
    return fun


def ml_usage(fun):
    """Indicate usage of the mailinglist realm.

    This is intended as decorator to signal a call into the mailinglist
    backend from a non-mailinglist frontend. The effect is to make the
    moderator information available which is normally only supplied if
    requesting an endpoint in the mailinglist realm.

    :type fun: callable
    :rtype: callable
    """
    if hasattr(fun, 'realm_usage'):
        fun.realm_usage.add('ml')
    else:
        fun.realm_usage = {'ml'}
    return fun


def event_guard(argname="event_id", check_offline=False):
    """This decorator checks the access with respect to a specific event. The
    event is specified by id which has either to be a keyword
    parameter or the first positional parameter after the request state.

    The event has to be organized via the DB. Only orgas and privileged
    users are admitted. Additionally this can check for the offline
    lock, so that no modifications happen to locked events.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    :type check_offline: bool
    :param check_offline: defaults to False
    """

    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.orga and not obj.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(
                    rs.gettext("This page can only be accessed by orgas."))
            if check_offline:
                is_locked = obj.eventproxy.is_offline_locked(rs, event_id=arg)
                if is_locked != obj.conf.CDEDB_OFFLINE_DEPLOYMENT:
                    raise werkzeug.exceptions.Forbidden(
                        rs.gettext("This event is locked for offline usage."))
            return fun(obj, rs, *args, **kwargs)

        return new_fun

    return wrap


def mailinglist_guard(argname="mailinglist_id"):
    """This decorator checks the access with respect to a specific
    mailinglist. The list is specified by id which has either to be a
    keyword parameter or the first positional parameter after the
    request state. Only moderators and privileged users are admitted.

    :type argname: str
    :param argname: name of the keyword argument specifying the id
    """

    def wrap(fun):
        @functools.wraps(fun)
        def new_fun(obj, rs, *args, **kwargs):
            if argname in kwargs:
                arg = kwargs[argname]
            else:
                arg = args[0]
            if arg not in rs.user.moderator and not obj.is_admin(rs):
                raise werkzeug.exceptions.Forbidden(rs.gettext(
                    "This page can only be accessed by the mailinglist’s "
                    "moderators."))
            return fun(obj, rs, *args, **kwargs)

        return new_fun

    return wrap


def check_validation(rs, assertion, value, name=None, **kwargs):
    """Helper to perform parameter sanitization.

    :type rs: :py:class:`RequestState`
    :type assertion: str
    :param assertion: name of validation routine to call
    :type value: object
    :type name: str or None
    :param name: name of the parameter to check (bonus points if you find
      out how to nicely get rid of this -- python has huge introspection
      capabilities, but I didn't see how this should be done).
    :rtype: (object or None, [(str, Exception)])
    """
    checker = getattr(validate, "check_{}".format(assertion))
    if name is not None:
        ret, errs = checker(value, name, **kwargs)
    else:
        ret, errs = checker(value, **kwargs)
    rs.errors.extend(errs)
    return ret


def basic_redirect(rs, url):
    """Convenience wrapper around :py:func:`construct_redirect`. This should
    be the main thing to use, however it is even more preferable to use
    :py:meth:`BaseApp.redirect`.

    :type rs: :py:class:`RequestState`
    :type url: str
    :rtype: :py:class:`werkzeug.wrappers.Response`
    """
    rs.response = construct_redirect(rs.request, url)
    rs.response.headers.add('X-Generation-Time', str(now() - rs.begin))
    return rs.response


def construct_redirect(request, url):
    """Construct an HTTP redirect. This should use the 303 status
    code. Unfortunately this code is not available for HTTP 1.0, so we fall
    back to an automatic refresh.

    :type request: :py:class:`werkzeug.wrappers.Request`
    :type url: str
    :rtype: :py:class:`werkzeug.wrappers.Response`
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


def make_postal_address(persona):
    """Prepare address info for formatting.

    Addresses have some specific formatting wishes, so we are flexible
    in that we represent an address to be printed as a list of strings
    each containing one line. The final formatting is now basically join
    on line breaks.

    :type persona: {str: object}
    :rtype: [str]
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


def make_transaction_subject(persona):
    """Generate a string for users to put on a payment.

    This is the "Verwendungszweck".

    :type persona: {str: object}
    :rtype: str
    """
    return "{}, {}, {}".format(cdedbid_filter(persona['id']),
                               asciificator(persona['family_name']),
                               asciificator(persona['given_names']))


class CustomCSVDialect(csv.Dialect):
    delimiter = ';'
    quoting = csv.QUOTE_MINIMAL
    quotechar = '"'
    doublequote = True
    lineterminator = '\n'
    escapechar = None


def csv_output(data, fields, writeheader=True, replace_newlines=False,
               substitutions=None):
    """Generate a csv representation of the passed data.

    :type data: [{str: object}]
    :type fields: [str]
    :type writeheader: bool
    :param writeheader: If False, no CSV-Header is written.
    :type replace_newlines: bool
    :param replace_newlines: If True all line breaks are replaced by several
      spaces.
    :type substitutions: {str: {object: object}}
    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    :rtype: str
    """
    substitutions = substitutions or {}
    outfile = io.StringIO()
    writer = csv.DictWriter(
        outfile, fields, dialect=CustomCSVDialect)
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


def query_result_to_json(data, fields, substitutions=None):
    """Generate a json representation of the passed data.

    :type data: [{str: object}]
    :type fields: [str]
    :type substitutions: {str: {object: object}}
    :param substitutions: Allow replacements of values with better
      representations for output. The key of the outer dict is the field
      name.
    :rtype: str
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
