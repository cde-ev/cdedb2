#!/usr/bin/env python3

"""Global utility functions."""

import collections
import collections.abc
import copy
import datetime
import decimal
import enum
import functools
import hmac
import icu
import inspect
import itertools
import json
import logging
import logging.handlers
import pathlib
import re
import shutil
import string
import sys
import hashlib
from typing import (
    Any, TypeVar, Mapping, Collection, Dict, List
)

import psycopg2.extras
import pytz
import werkzeug.datastructures

# The following imports are only for re-export. They are not used
# here. All other uses should import them from here and not their
# original source which is basically just uninlined code.
from cdedb.ml_subscription_aux import (
    SubscriptionError, SubscriptionInfo, SubscriptionActions)

_LOGGER = logging.getLogger(__name__)

# Global unified collator to be used when sorting.
COLLATOR = icu.Collator.createInstance(icu.Locale('de_DE.UTF-8@colNumeric=yes'))

# Pseudo objects like assembly, event, course, event part, etc.
CdEDBObject = Mapping[str, Any]
# Dict-like list of pseudo objects, indexed by their id, as returned by
# `get_events`, event["parts"], etc.
CdEDBObjectList = Mapping[int, CdEDBObject]
# An integer with special semantics. Positive return values indicate success,
# a return of zero signals an error, a negative return value indicates some
# special case like a change pending review.
DefaultReturnCode = int
# Return value for `delete_foo_blockers` part of the deletion interface.
# The key specifies the kind of blocker, the value is a list of blocking ids.
# For some blockers the value might have a different type, mostly when that
# blocker blocks deletion without the option to cascadingly delete.
DeletionBlockers = Dict[str, List[int]]


class RequestState:
    """Container for request info. Besides this and db accesses the python
    code should be state-less. This data structure enables several
    convenient semi-magic behaviours (magic enough to be nice, but non-magic
    enough to not be non-nice).
    """

    def __init__(self, sessionkey, apitoken, user, request, response,
                 notifications, mapadapter, requestargs, errors, values, lang,
                 gettext, ngettext, coders, begin, default_gettext=None,
                 default_ngettext=None):
        """
        :type sessionkey: str or None
        :type apitoken: str or None
        :type user: :py:class:`User`
        :type request: :py:class:`werkzeug.wrappers.Request`
        :type response: :py:class:`werkzeug.wrappers.Response` or None
        :type notifications: [(str, str, {str: object})]
        :param notifications: Messages to be displayed to the user. To be
          submitted by :py:meth:`notify`. The parameters are
            * the type of message (e.g. warning),
            * the message string,
            * a (possibly empty) dict describing substitutions to be done on
              the message string (after i18n).
        :type mapadapter: :py:class:`werkzeug.routing.MapAdapter`
        :param mapadapter: URL generator (specific for this request)
        :type requestargs: {str: object}
        :param requestargs: verbatim copy of the arguments contained in the URL
        :type errors: [(str, exception)]
        :param errors: Validation errors, consisting of a pair of (parameter
          name, the actual error). The exceptions have one or two
          parameters. First a string being the error message. And second an
          optional {str: object} dict, describing substitutions to be done
          after i18n.
        :type values: {str: object}
        :param values: Parameter values extracted via :py:func:`REQUESTdata`
          and :py:func:`REQUESTdatadict` decorators, which allows automatically
          filling forms in. This will be a
          :py:class:`werkzeug.datastructures.MultiDict` to allow seamless
          integration with the werkzeug provided data.
        :type lang: str
        :param lang: language code for i18n, currently only 'de' is valid
        :type gettext: callable
        :param gettext: translation function as in the gettext module
        :type ngettext: callable
        :param ngettext: translation function as in the gettext module
        :type coders: {str: callable}
        :param coders: Functions for encoding and decoding parameters primed
          with secrets. This is hacky, but sadly necessary.
        :type begin: datetime.datetime
        :param begin: time where we started to process the request
        :type default_gettext: callable
        :param default_gettext: default translation function used to ensure
            stability across different locales
        :type default_ngettext: callable
        :param default_ngettext: default translation function used to ensure
            stability across different locales
        """
        self.ambience = {}
        self.sessionkey = sessionkey
        self.apitoken = apitoken
        self.user = user
        self.request = request
        self.response = response
        self.notifications = notifications
        self.urls = mapadapter
        self.requestargs = requestargs
        self._errors = errors
        if not isinstance(values, werkzeug.datastructures.MultiDict):
            values = werkzeug.datastructures.MultiDict(values)
        self.values = values
        self.lang = lang
        self.gettext = gettext
        self.ngettext = ngettext
        self.default_gettext = default_gettext or gettext
        self.default_ngettext = default_ngettext or ngettext
        self._coders = coders
        self.begin = begin
        # Visible version of the database connection
        self.conn = None
        # Private version of the database connection, only visible in the
        # backends (mediated by the ProxyShim)
        self._conn = None
        # Toggle to disable logging
        self.is_quiet = False
        # Is true, if the application detected an invalid (or no) CSRF token
        self.csrf_alert = False
        # Used for validation enforcement, set to False if a validator
        # is executed and then to True with the corresponding methods
        # of this class
        self.validation_appraised = None

    def notify(self, ntype, message, params=None):
        """Store a notification for later delivery to the user.

        :type ntype: str
        :param ntype: one of :py:data:`NOTIFICATION_TYPES`
        :type message: str
        :type params: set or None
        """
        if ntype not in NOTIFICATION_TYPES:
            raise ValueError(n_("Invalid notification type %(t)s found."),
                             {'t': ntype})
        params = params or {}
        self.notifications.append((ntype, message, params))

    def append_validation_error(self, error):
        """Register a new  error.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.

        However in general the method extend_validation_errors()
        should be preferred since it activates the validation tracking
        even if no errors are present.

        :type error: (str, Exception)
        """
        self.validation_appraised = False
        self._errors.append(error)

    def extend_validation_errors(self, errors):
        """Register a new (maybe empty) set of errors.

        The important side-effect is the activation of the validation
        tracking, that causes the application to throw an error if the
        validation result is not checked.

        :type errors: [(str, Exception)]
        """
        self.validation_appraised = False
        self._errors.extend(errors)

    def has_validation_errors(self):
        """Check whether validation errors exists.

        This (or its companion function) must be called in the
        lifetime of a request. Otherwise the application will throw an
        error.

        :rtype: bool
        """
        self.validation_appraised = True
        return bool(self._errors)

    def ignore_validation_errors(self):
        """Explicitly mark validation errors as irrelevant.

        This (or its companion function) must be called in the
        lifetime of a request. Otherwise the application will throw an
        error.
        """
        self.validation_appraised = True

    def retrieve_validation_errors(self):
        """Take a look at the queued validation errors.

        This does not cause the validation tracking to register a
        successful check.

        :rtype: [(str, Exception)]
        """
        return self._errors


class User:
    """Container for a persona."""

    def __init__(self, persona_id=None, roles=None, display_name="",
                 given_names="", family_name="", username="", orga=None,
                 moderator=None):
        """
        :type persona_id: int or None
        :type roles: {str}
        :param roles: python side privilege levels
        :type display_name: str or None
        :type given_names: str or None
        :type family_name or None
        :type username: str or None
        :type orga: [int]
        :type moderator: [int]
        """
        self.persona_id = persona_id
        self.roles = roles or {"anonymous"}
        self.username = username
        self.display_name = display_name
        self.given_names = given_names
        self.family_name = family_name
        self.orga = orga or []
        self.moderator = moderator or []
        self.admin_views = set()

    @property
    def available_admin_views(self):
        return roles_to_admin_views(self.roles)

    def init_admin_views_from_cookie(self, enabled_views_cookie):
        enabled_views = enabled_views_cookie.split(',')
        self.admin_views = self.available_admin_views & set(enabled_views)


class ProxyShim:
    """Wrap a backend for some syntactic sugar.

    If we used an actual RPC mechanism, this would do some additional
    lifting to accomodate this.

    This takes care of the annotations given by the decorators on the
    backend functions.
    """

    def __init__(self, backend, internal=False):
        """
        :type backend: :py:class:`AbstractBackend`
        """
        self._backend = backend
        self._funs = {}
        self._internal = internal
        funs = inspect.getmembers(backend, predicate=inspect.isroutine)
        for name, fun in funs:
            if hasattr(fun, "access_list") or (
                    internal and hasattr(fun, "internal_access_list")):
                self._funs[name] = self._wrapit(fun)

    def _wrapit(self, fun):
        """
        :type fun: callable
        """
        try:
            access_list = fun.access_list
        except AttributeError:
            if self._internal:
                access_list = fun.internal_access_list
            else:
                raise

        @functools.wraps(fun)
        def new_fun(rs, *args, **kwargs):
            if rs.user.roles & access_list:
                try:
                    if not self._internal:
                        # Expose database connection for the backends
                        rs.conn = rs._conn
                    return fun(rs, *args, **kwargs)
                finally:
                    if not self._internal:
                        rs.conn = None
            else:
                raise PrivilegeError(n_("Not in access list."))

        return new_fun

    def __getattr__(self, name):
        if name in {"_funs", "_backend"}:
            raise AttributeError()
        try:
            return self._funs[name]
        except KeyError as e:
            raise AttributeError from e


def make_root_logger(name, logfile_path, log_level, syslog_level=None,
                     console_log_level=None):
    """Configure the :py:mod:`logging` module. Since this works hierarchical,
    it should only be necessary to call this once and then every child
    logger is routed through this configured logger.

    :type name: str
    :type logfile_path: str or pathlib.Path
    :type log_level: int
    :type syslog_level: int or None
    :type console_log_level: int or None
    :rtype: logging.Logger
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.info("Logger {} already initialized.".format(name))
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
    logger.info("Configured logger {}.".format(name))
    return logger


def glue(*args):
    """Join overly long strings, adds boundary white space for convenience.

    It would be possible to use auto string concatenation as in ``("a
    string" "another string")`` instead, but there you have to be
    careful to add boundary white space yourself, so we prefer this
    explicit function.

    :type args: [str]
    :rtype: str
    """
    return " ".join(args)


def merge_dicts(*dicts):
    """Merge all dicts into the first one, but do not overwrite.

    This is basically the :py:meth:`dict.update` method, but existing
    keys take precedence.

    This is done inplace to allow the target dict to be a multi dict. If
    we create a new return dict we would have to add extra logic to
    cater for this.

    Additionally if the target is a MultiDict we use the correct method for
    setting list-type values.

    :type dicts: [{object: object}]
    """
    assert (len(dicts) > 0)
    for adict in dicts[1:]:
        for key in adict:
            if key not in dicts[0]:
                if (isinstance(adict[key], collections.abc.Sequence)
                        and not isinstance(adict[key], str)
                        and isinstance(dicts[0], werkzeug.MultiDict)):
                    dicts[0].setlist(key, adict[key])
                else:
                    dicts[0][key] = adict[key]


def get_hash(obj: Any) -> str:
    """Helper to calculate a hexadecimal has of an arbitrary object."""
    hasher = hashlib.sha512()
    hasher.update(obj)
    return hasher.hexdigest()


def now():
    """Return an up to date timestamp.

    This is a separate function so we do not forget to make it time zone
    aware.

    :rtype: datetime.datetime
    """
    return datetime.datetime.now(pytz.utc)


class QuotaException(RuntimeError):
    """
    Exception for signalling a quota excess. This is thrown in
    :py:mod:`cdedb.backend.cde` and caught in
    :py:mod:`cdedb.frontend.application`. We use a custom class so that
    we can distinguish it from other exceptions.
    """
    pass


class PrivilegeError(RuntimeError):
    """
    Exception for signalling missing privileges. This Exception is thrown by the
    backend to indicate an unprivileged call to a backend function. However,
    this situation should be prevented by privilege checks in the frontend.
    Thus, we typically consider this Exception as an unexpected programming
    error. In some cases the frontend may catch and handle the exception
    instead of preventing it in the first place.
    """
    pass


class ArchiveError(RuntimeError):
    """
    Exception for signalling an exact error when archiving a persona
    goes awry.
    """
    pass


class PartialImportError(RuntimeError):
    """Exception for signalling a checksum mismatch in the partial import.

    Making this an exception rolls back the database transaction.
    """
    pass


class ValidationWarning(Exception):
    """Exception which should be suppressable by the user."""
    pass


def xsorted(iterable, *, key=lambda x: x, reverse=False):
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

    :type iterable: iterable
    :param key: function to order by
    :type key: callable
    :type reverse: boolean
    :rtype: list
    """

    def collate(sortkey):
        if isinstance(sortkey, str):
            return COLLATOR.getSortKey(sortkey)
        if isinstance(sortkey, collections.abc.Iterable):
            # Make sure strings in nested Iterables are sorted
            # correctly as well.
            return tuple(map(collate, sortkey))
        return sortkey

    return sorted(iterable, key=lambda x: collate(key(x)),
                  reverse=reverse)


class EntitySorter:
    """Provide a singular point for common sortkeys.

    This class does not need to be instantiated. It's method can be passed to
    `sorted` or `keydictsort_filter`.
    """

    # TODO decide whether we sort by first or last name
    @staticmethod
    def persona(entry):
        """Create a sorting key associated to a persona dataset.

        This way we have a standardized sorting order for entries.

        :type entry: {str: object}
        :param entry: A dataset of a persona from the cde or event realm.
        :rtype: str
        """
        return (entry['family_name'] + " " + entry['given_names']).lower()

    @staticmethod
    def given_names(persona):
        return persona['given_names']

    @staticmethod
    def family_name(persona):
        return persona['family_name']

    @staticmethod
    def email(persona):
        return persona['username']

    @staticmethod
    def address(persona):
        postal_code = persona.get('postal_code', "") or ""
        location = persona.get('location', "") or ""
        address = persona.get('address', "") or ""
        return (postal_code, location, address)

    @staticmethod
    def event(event):
        return (event['begin'], event['end'], event['title'], event['id'])

    @staticmethod
    def course(course):
        return (course['nr'], course['shortname'], course['id'])

    @staticmethod
    def lodgement(lodgement):
        return (lodgement['moniker'], lodgement['id'])

    @staticmethod
    def lodgement_group(lodgement_group):
        return (lodgement_group['moniker'], lodgement_group['id'])

    @staticmethod
    def event_part(event_part):
        return (event_part['part_begin'], event_part['part_end'],
                event_part['shortname'], event_part['id'])

    @staticmethod
    def course_track(course_track):
        return (course_track['sortkey'], course_track['id'])

    @staticmethod
    def event_field(event_field):
        return (event_field['field_name'], event_field['id'])

    @staticmethod
    def candidates(candidates):
        return (candidates['moniker'], candidates['id'])

    @staticmethod
    def assembly(assembly):
        return (assembly['signup_end'], assembly['id'])

    @staticmethod
    def ballot(ballot):
        return (ballot['title'], ballot['id'])

    @staticmethod
    def attachment(attachment):
        return (attachment['title'], attachment['id'])

    @staticmethod
    def attachment_version(version):
        return (version['attachment_id'], version['version'])

    @staticmethod
    def past_event(past_event):
        return (past_event['tempus'], past_event['id'])

    @staticmethod
    def past_course(past_course):
        return (past_course['nr'], past_course['title'], past_course['id'])

    @staticmethod
    def institution(institution):
        return (institution['moniker'], institution['id'])

    @staticmethod
    def transaction(transaction):
        return (transaction['issued_at'], transaction['id'])

    @staticmethod
    def genesis_case(genesis_case):
        return (genesis_case['ctime'], genesis_case['id'])

    @staticmethod
    def changelog(changelog_entry):
        return (changelog_entry['ctime'], changelog_entry['id'])

    @staticmethod
    def mailinglist(mailinglist):
        return (mailinglist['title'], mailinglist['id'])


def compute_checkdigit(value):
    """Map an integer to the checksum used for UI purposes.

    This checkdigit allows for error detection if somebody messes up a
    handwritten ID or such.

    Most of the time, the integer will be a persona id.

    :type value: int
    :rtype: str
    """
    digits = []
    tmp = value
    while tmp > 0:
        digits.append(tmp % 10)
        tmp = tmp // 10
    dsum = sum((i + 2) * d for i, d in enumerate(digits))
    return "0123456789X"[-dsum % 11]


def lastschrift_reference(persona_id, lastschrift_id):
    """Return an identifier for usage with the bank.

    This is the so called 'Mandatsreferenz'.

    :type persona_id: int
    :type lastschrift_id: int
    :rtype: str
    """
    return "CDE-I25-{}-{}-{}-{}".format(
        persona_id, compute_checkdigit(persona_id), lastschrift_id,
        compute_checkdigit(lastschrift_id))


def _small_int_to_words(num, lang):
    """Convert a small integer into a written representation.

    Helper for the general function.

    :type num: int
    :param num: Must be between 0 and 999
    :type lang: str
    :param lang: Currently we only suppert 'de'.
    :rtype: str
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


def int_to_words(num, lang):
    """Convert an integer into a written representation.

    This is for the usage such as '2 apples' -> 'two apples'.

    :type num: int
    :type lang: str
    :param lang: Currently we only suppert 'de'.
    :rtype: str
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

    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return str(obj)
        elif isinstance(obj, set):
            return tuple(obj)
        return super().default(obj)


def json_serialize(data, **kwargs):
    """Do beefed up JSON serialization.

    :type data: obj
    :rtype: str
    """
    return json.dumps(data, indent=4, cls=CustomJSONEncoder, **kwargs)


class PsycoJson(psycopg2.extras.Json):
    """Json encoder for consumption by psycopg.

    This is the official way of customizing the serialization process by
    subclassing the appropriate class.
    """

    def dumps(self, obj):
        return json_serialize(obj)


def shutil_copy(*args, **kwargs):
    """Wrapper around shutil.copy() converting pathlib.Path to str.

    This is just a convenience function.
    """
    args = tuple(str(a) if isinstance(a, pathlib.Path) else a for a in args)
    kwargs = {k: str(v) if isinstance(v, pathlib.Path) else v
              for k, v in kwargs.items()}
    return shutil.copy(*args, **kwargs)


def pairwise(iterable):
    """Iterate over adjacent pairs of values of an iterable.

    For the input [1, 3, 6, 10] this returns [(1, 3), (3, 6), (6, 10)].

    :type iterable: iterable
    :rtype: iterable
    """
    x, y = itertools.tee(iterable)
    next(y, None)
    return zip(x, y)


def _schulze_winners(d, candidates):
    """This is the abstract part of the Schulze method doing the actual work.

    The candidates are the vertices of a graph and the metric (in form
    of ``d``) describes the strength of the links between the
    candidates, that is edge weights.

    We determine the strongest path from each vertex to each other
    vertex. This gives a transitive relation, which enables us thus to
    determine winners as maximal elements.

    :type d: {(str, str): int}
    :type candidates: [str]
    :rtype: [str]
    """
    # First determine the strongst paths
    p = {(x, y): d[(x, y)] for x in candidates for y in candidates}
    for i in candidates:
        for j in candidates:
            if i == j:
                continue
            for k in candidates:
                if i == k or j == k:
                    continue
                p[(j, k)] = max(p[(j, k)], min(p[(j, i)], p[(i, k)]))
    # Second determine winners
    winners = []
    for i in candidates:
        if all(p[(i, j)] >= p[(j, i)] for j in candidates):
            winners.append(i)
    return winners


def schulze_evaluate(votes, candidates):
    """Use the Schulze method to cummulate preference list into one list.

    This is used by the assembly realm to tally votes -- however this is
    pretty abstract, so we move it here.

    Votes have the form ``3>0>1=2>4`` where the monikers between the
    relation signs are exactly those passed in the ``candidates`` parameter.

    The Schulze method is described in the pdf found in the ``related``
    folder. Also the Wikipedia article is pretty nice.

    One thing to mention is, that we do not do any tie breaking. Since
    we allow equality in the votes, it seems reasonable to allow
    equality in the result too.

    For a nice set of examples see the test suite.

    :type votes: [str]
    :type candidates: [str]
    :param candidates: We require that the candidates be explicitly
      passed. This allows for more flexibility (like returning a useful
      result for zero votes).
    :rtype: (str, [{}])
    :returns: The first Element is the aggregated result,
    the second is an more extended list, containing every level (descending) as
    dict with some extended information.
    """
    split_votes = tuple(
        tuple(level.split('=') for level in vote.split('>')) for vote in votes)

    def _subindex(alist, element):
        """The element is in the list at which position in the big list.

        :type alist: [[str]]
        :type element: str
        :rtype: int
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
    def _strength(support, opposition, totalvotes):
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

        :type support: int
        :type opposition: int
        :type totalvotes: int
        :rtype: int
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
    result = []
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
        level = {
            'winner': lead,
            'loser': follow,
            'pro_votes': counts[(lead[0], follow[0])],
            'contra_votes': counts[(follow[0], lead[0])]
        }
        detailed.append(level)

    return condensed, detailed


#: Magic value of moniker of the ballot candidate representing the bar.
ASSEMBLY_BAR_MONIKER = "_bar_"

T = TypeVar("T")


# The following two functions are different versions of unwrap, to make
# the typechecker happy.
def unwrap_values(mapping: Mapping[Any, T]) -> T:
    return next(i for i in mapping.values())


def unwrap_keys(mapping: Mapping[T, Any]) -> T:
    return next(i for i in mapping.keys())


def unwrap(single_element_list: Collection[T], keys: bool = False) -> T:
    """Remove one nesting layer (of lists, etc.).

    This is here to replace code like ``foo = bar[0]`` where bar is a
    list with a single element. This offers some more amenities: it
    works on dicts and performs validation.

    In case of an error (e.g. wrong number of elements) this raises an
    error.

    :param keys: If a mapping is input, this toggles between returning
      the key or value.
    """
    if (not isinstance(single_element_list, collections.abc.Iterable)
            or (isinstance(single_element_list, collections.abc.Sized)
                and len(single_element_list) != 1)):
        raise RuntimeError(n_("Unable to unwrap!"))
    if isinstance(single_element_list, collections.abc.Mapping):
        if keys:
            single_element_list = single_element_list.keys()
        else:
            single_element_list = single_element_list.values()
    return next(i for i in single_element_list)


@enum.unique
class LodgementsSortkeys(enum.Enum):
    """Sortkeys for lodgement overview."""
    #: default sortkey (currently equal to EntitySorter.lodgement)
    moniker = 1
    #: (capacity - reserve) which are used in this part
    used_regular = 10
    #: reserve which is used in this part
    used_reserve = 11
    #: (capacity - reserve) of this lodgement
    total_regular = 20
    #: reserve of this lodgement
    total_reserve = 21

    def is_used_sorting(self):
        return self in (LodgementsSortkeys.used_regular,
                        LodgementsSortkeys.used_reserve)

    def is_total_sorting(self):
        return self in (LodgementsSortkeys.total_regular,
                        LodgementsSortkeys.total_reserve)


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

    def is_minor(self):
        """Checks whether a legal guardian is required.

        :rtype: bool
        """
        return self in {AgeClasses.u14, AgeClasses.u16, AgeClasses.u18}

    def may_mix(self):
        """Whether persons of this age may be legally accomodated in a mixed
        lodging together with the opposite gender.

        :rtype: bool
        """
        return self in {AgeClasses.full, AgeClasses.u18}


def deduct_years(date, years):
    """Convenience function to go back in time.

    Dates are nasty, in theory this should be a simple subtraction, but
    leap years create problems.

    :type date: datetime.date
    :type years: int
    :rtype: datetime.date
    """
    try:
        return date.replace(year=date.year - years)
    except ValueError:
        # this can happen in only one situation: we tried to move a leap
        # day into a year without leap
        assert (date.month == 2 and date.day == 29)
        return date.replace(year=date.year - years, day=28)


def determine_age_class(birth, reference):
    """Basically a constructor for :py:class:`AgeClasses`.

    :type birth: datetime.date
    :type reference: datetime.date
    :param reference: Time at which to check age status (e.g. the first day of
      a scheduled event).
    :rtype: :py:class:`AgeClasses`
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

    def do_trial(self):
        """Whether to grant a trial membership.

        :rtype: bool
        """
        return self in {LineResolutions.renew_trial,
                        LineResolutions.renew_and_update}

    def do_update(self):
        """Whether to incorporate the new data (address, ...).

        :rtype: bool
        """
        return self in {LineResolutions.update,
                        LineResolutions.renew_and_update}

    def is_modification(self):
        """Whether we modify an existing account.

        In this case we do not create a new account.

        :rtype: bool
        """
        return self in {LineResolutions.renew_trial,
                        LineResolutions.update,
                        LineResolutions.renew_and_update}


#: magic number which signals our makeshift algebraic data type
INFINITE_ENUM_MAGIC_NUMBER = 0


def infinite_enum(aclass):
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

    In the code they are stored as an :py:data:`InfiniteEnum`.

    :type aclass: obj
    :rtype: obj

    """
    return aclass


#: Storage facility for infinite enums with associated data, see
#: :py:func:`infinite_enum`
@functools.total_ordering
class InfiniteEnum:
    def __init__(self, enum, int):
        self.enum = enum
        self.int = int

    @property
    def value(self):
        if self.enum == INFINITE_ENUM_MAGIC_NUMBER:
            return self.int
        return self.enum.value

    def __str__(self):
        if self.enum == INFINITE_ENUM_MAGIC_NUMBER:
            return "{}({})".format(self.enum, self.int)
        return str(self.enum)

    def __eq__(self, other):
        if isinstance(other, InfiniteEnum):
            return self.value == other.value
        if isinstance(other, int):
            return self.value == other
        return NotImplemented

    def __lt__(self, other):
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

    def __str__(self):
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
    def has_event(self):
        return self in {TransactionType.EventFee,
                        TransactionType.EventFeeRefund,
                        TransactionType.InstructorRefund,
                        TransactionType.EventExpenses,
                        }

    @property
    def has_member(self):
        return self in {TransactionType.MembershipFee,
                        TransactionType.EventFee,
                        TransactionType.I25p,
                        }

    @property
    def is_unknown(self):
        return self in {TransactionType.Unknown,
                        TransactionType.Other,
                        TransactionType.OtherPayment
                        }

    def old(self):
        """
        Return a string representation compatible with the old excel style.

        :rtype: str
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

    def __str__(self):
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
                     TransactionType.EventFeeRefund.name: "Teilnehmererstattung",
                     TransactionType.InstructorRefund.name: "KL-Erstattung",
                     TransactionType.EventExpenses.name: "Veranstaltungsausgabe",
                     TransactionType.Expenses.name: "Ausgabe",
                     TransactionType.AccountFee.name: "Kontogebühr",
                     TransactionType.OtherPayment.name: "Andere Zahlung",
                     TransactionType.Unknown.name: "Unbekannt",
                     }
        if self.name in to_string:
            return to_string[self.name]
        else:
            return repr(self)


def mixed_existence_sorter(iterable):
    """Iterate over a set of indices in the relevant way.

    That is first over the non-negative indices in ascending order and
    then over the negative indices in descending order.

    This is the desired order if the UI offers the possibility to
    create multiple new entities enumerated by negative IDs.

    :type iterable: [int]
    """
    for i in xsorted(iterable):
        if i >= 0:
            yield i
    for i in reversed(xsorted(iterable)):
        if i < 0:
            yield i


def n_(x):
    """
    Alias of the identity for i18n.
    Identity function that shadows the gettext alias to trick pybabel into
    adding string to the translated strings.
    """
    return x


def asciificator(s):
    """Pacify a string.

    Replace or omit all characters outside a known good set. This is to
    be used if your use case does not tolerate any fancy characters
    (like SEPA files).

    :type s: str
    :rtype: str
    """
    umlaut_map = {
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
    ret = ""
    for char in s:
        if char in umlaut_map:
            ret += umlaut_map[char]
        elif char in (string.ascii_letters + string.digits + " /-?:().,+"):
            ret += char
        else:
            ret += ' '
    return ret


def diacritic_patterns(s, two_way_replace=False):
    """Replace letters with a pattern matching expressions.

    Thus ommitting diacritics in the query input is possible.

    This is intended for use with regular expressions.

    :type s: str or None
    :type two_way_replace: bool
    :param two_way_replace: If this is True, replace all letter with a
      potential diacritic (independent of the presence of the diacritic)
      with a pattern matching all diacritic variations. If this is False
      only replace in case of no diacritic present.

      This can be used to search for occurences of names stored
      in the db within input, that may not contain proper diacritics
      (e.g. it may be constrained to ASCII).
    :rtype: str or None
    """
    if s is None:
        return s
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


def encode_parameter(salt, target, name, param,
                     timeout=datetime.timedelta(seconds=60)):
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

    All ingredients used here are necessary for security. The timestamp
    guarantees a short lifespan via the decoding function.

    The message format is A--B--C, where

    * A is 128 chars sha512 checksum of 'X--Y--Z--B--C' where X == salt, Y
      == target, Z == name
    * B is 24 chars timestamp of format '%Y-%m-%d %H:%M:%S%z' or 24 dots
      describing when the parameter expires (and the latter meaning never)
    * C is an arbitrary amount chars of payload

    :type salt: str
    :param salt: secret used for signing the parameter
    :type target: str
    :param target: The endpoint the parameter is designated for. If this is
      omitted, there are nasty replay attacks.
    :type name: str
    :param name: name of parameter, same security implications as ``target``
    :type param: str
    :param timeout: time until parameter expires, if this is None, the
      parameter never expires
    :type timeout: datetime.timedelta or None
    :rtype: str
    """
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    if timeout is None:
        timestamp = 24 * '.'
    else:
        ttl = now() + timeout
        timestamp = ttl.strftime("%Y-%m-%d %H:%M:%S%z")
    message = "{}--{}".format(timestamp, param)
    tohash = "{}--{}--{}".format(target, name, message)
    h.update(tohash.encode("utf-8"))
    return "{}--{}".format(h.hexdigest(), message)


def decode_parameter(salt, target, name, param):
    """Inverse of :py:func:`encode_parameter`. See there for
    documentation.

    :type salt: str
    :type target: str
    :type name: str
    :type param: str
    :rtype: (bool or None, str or None)
    :returns: The string is the decoded message or ``None`` if any failure
      occured. The boolean is True if the failure was a timeout, False if
      the failure was something else and None if no failure occured.
    """
    h = hmac.new(salt.encode('ascii'), digestmod="sha512")
    mac, message = param[0:128], param[130:]
    tohash = "{}--{}--{}".format(target, name, message)
    h.update(tohash.encode("utf-8"))
    if not hmac.compare_digest(h.hexdigest(), mac):
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


def extract_roles(session, introspection_only=False):
    """Associate some roles to a data set.

    The data contains the relevant portion of attributes from the
    core.personas table. We have some more logic than simply grabbing
    the flags from the dict like only allowing admin privileges in a
    realm if access to the realm is already granted.

    Note that this also works on non-personas (i.e. dicts of is_* flags).

    :type session: {str: object}
    :type introspection_only: bool
    :param introspection_only: If True the result should only be used to
      take an extrinsic look on a persona and not the determine the privilege
      level of the data set passed.
    :rtype: {str}
    """
    ret = {"anonymous"}
    if session['is_active']:
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
    if "cde_admin" in ret:
        if session.get("is_finance_admin"):
            ret.add("finance_admin")
    return ret


# The following droids are exempt from lockdown to keep our infrastructure
# working
INFRASTRUCTURE_DROIDS = {'rklist', 'resolve'}


def droid_roles(identity):
    """Resolve droid identity to a complete set of roles.

    Currently this is rather trivial, but could be more involved in the
    future if more API capabilities are added to the DB.

    :type identity: str
    :param identity: The name for the API functionality, e.g. ``rklist``.
    :rtype: {str}
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
REALM_INHERITANCE = {
    'cde': {'event', 'assembly', 'ml'},
    'event': {'ml'},
    'assembly': {'ml'},
    'ml': set(),
}


def extract_realms(roles):
    """Get the set of realms from a set of user roles.

    When checking admin privileges, we must often check, if the user's realms
    are a subset of some other set of realms. To help with this, this function
    helps with this task, by extracting only the actual realms from a user's
    set of roles.

    :param roles: All roles of a user
    :type roles: {str}
    :return: The realms the user is member of
    :rtype: {str}
    """
    return roles & REALM_INHERITANCE.keys()


def implied_realms(realm):
    """Get additional realms implied by membership in one realm

    :param realm: The name of the realm to check
    :type realm: str
    :return: A set of the names of all implied realms
    :rtype: {str}
    """
    return REALM_INHERITANCE.get(realm, set())


def implying_realms(realm):
    """Get all realms where membership implies the given realm.

    This can be used to determine the realms in which a user must *not* be to be
    listed in a specific realm or be edited by its admins.

    :param realm: The realm to search implying realms for
    :type realm: str
    :return: A set of all realms implying
    """
    return set(r
               for r, implied in REALM_INHERITANCE.items()
               if realm in implied)


def privilege_tier(roles, conjunctive=False):
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

    :type roles: {str}
    :type conjunctive: bool
    :rtype: [{str}]
    :returns: List of sets of admin roles. Any of these sets is sufficient.

    """
    # Get primary user realms (those, that don't imply other realms)
    relevant = roles & REALM_INHERITANCE.keys()
    if relevant:
        implied_roles = set.union(*(
            REALM_INHERITANCE.get(k, set()) for k in relevant))
        relevant -= implied_roles
    if conjunctive:
        ret = ({realm + "_admin" for realm in relevant},
               {"core_admin"})
    else:
        ret = tuple({realm + "_admin"} for realm in relevant)
        ret += ({"core_admin"},)
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
}

#: Set of possible values for ``ntype`` in
#: :py:meth:`RequestState.notify`. Must conform to the regex
#: ``[a-z]+``.
NOTIFICATION_TYPES = {"success", "info", "question", "warning", "error"}

#: The form field name used for the anti CSRF token.
#: It should be added to all data modifying form using the
#: util.anti_csrf_token template macro and is check by the application.
ANTI_CSRF_TOKEN_NAME = "_anti_csrf"

#: Map of available privilege levels to those present in the SQL database
#: (where we have less differentiation for the sake of simplicity).
#:
#: This is an ordered dict, so that we can select the highest privilege
#: level.
DB_ROLE_MAPPING = collections.OrderedDict((
    ("meta_admin", "cdb_admin"),
    ("core_admin", "cdb_admin"),
    ("cde_admin", "cdb_admin"),
    ("ml_admin", "cdb_admin"),
    ("assembly_admin", "cdb_admin"),
    ("event_admin", "cdb_admin"),

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


def roles_to_db_role(roles):
    """Convert a set of application level roles into a database level role.

    :type roles: {str}
    :rtype: str
    """
    for role in DB_ROLE_MAPPING:
        if role in roles:
            return DB_ROLE_MAPPING[role]


ADMIN_VIEWS_COOKIE_NAME = "enabled_admin_views"

ALL_ADMIN_VIEWS = {
    "meta_admin", "core_user", "core", "cde_user", "past_event", "finance",
    "event_user", "event_mgmt", "event_orga", "ml_user", "ml_mgmt",
    "ml_moderator", "assembly_user", "assembly_mgmt", "assembly_contents",
    "genesis"}


def roles_to_admin_views(roles):
    """ Get the set of available admin views for a user with given roles.
    
    :type roles: {str} 
    :return: {str}
    """
    result = set()
    if "meta_admin" in roles:
        result |= {"meta_admin"}
    if "core_admin" in roles:
        result |= {"core_user", "core"}
    if "cde_admin" in roles:
        result |= {"cde_user", "past_event"}
    if "finance_admin" in roles:
        result |= {"finance"}
    if "event_admin" in roles:
        result |= {"event_user", "event_mgmt", "event_orga"}
    if "ml_admin" in roles:
        result |= {"ml_user", "ml_mgmt", "ml_moderator"}
    if "assembly_admin" in roles:
        result |= {"assembly_user", "assembly_mgmt", "assembly_contents"}
    if roles & ({'core_admin'} | set(
            "{}_admin".format(realm)
            for realm in realm_specific_genesis_fields)):
        result |= {"genesis"}
    return result


#: Version tag, so we know that we don't run out of sync with exported event
#: data. This has to be incremented whenever the event schema changes.
#: If you increment this, it must be incremented in make_offline_vm.py as well.
CDEDB_EXPORT_EVENT_VERSION = 10

#: Default number of course choices of new event course tracks
DEFAULT_NUM_COURSE_CHOICES = 3

#: All columns deciding on the current status of a persona
PERSONA_STATUS_FIELDS = (
    "is_active", "is_meta_admin", "is_core_admin", "is_cde_admin",
    "is_finance_admin", "is_event_admin", "is_ml_admin", "is_assembly_admin",
    "is_cde_realm", "is_event_realm", "is_ml_realm", "is_assembly_realm",
    "is_member", "is_searchable", "is_archived")

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_CORE_FIELDS = PERSONA_STATUS_FIELDS + (
    "id", "username", "display_name", "family_name", "given_names",
    "title", "name_supplement")

#: Names of columns associated to a cde (formor)member
PERSONA_CDE_FIELDS = PERSONA_CORE_FIELDS + (
    "gender", "birthday", "telephone", "mobile", "address_supplement",
    "address", "postal_code", "location", "country", "birth_name",
    "address_supplement2", "address2", "postal_code2", "location2",
    "country2", "weblink", "specialisation", "affiliation", "timeline",
    "interests", "free_form", "balance", "decided_search", "trial_member",
    "bub_search", "foto")

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
    "address", "postal_code", "location", "country", "birth_name", "attachment",
    "realm", "notes", "case_status", "reviewer")

# The following dict defines, which additional fields are required for genesis
# request for distinct realms. Additionally, it is used to define for which
# realms genesis requrests are allowed
realm_specific_genesis_fields = {
    "ml": tuple(),
    "event": ("gender", "birthday", "telephone", "mobile",
              "address_supplement", "address", "postal_code", "location",
              "country"),
    "cde": ("gender", "birthday", "telephone", "mobile",
            "address_supplement", "address", "postal_code", "location",
            "country", "birth_name", "attachment"),
}

genesis_realm_access_bits = {
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
    }
}

#: Fields of a pending privilege change.
PRIVILEGE_CHANGE_FIELDS = (
    "id", "ctime", "ftime", "persona_id", "submitted_by", "status",
    "is_meta_admin", "is_core_admin", "is_cde_admin",
    "is_finance_admin", "is_event_admin", "is_ml_admin",
    "is_assembly_admin", "notes", "reviewer")

#: Fields for institutions of events
INSTITUTION_FIELDS = ("id", "title", "moniker")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "shortname", "institution", "description",
                     "tempus", "notes")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "institution", "description", "shortname",
    "registration_start", "registration_soft_limit", "registration_hard_limit",
    "iban", "nonmember_surcharge", "orga_address", "registration_text",
    "mail_text", "use_questionnaire", "notes", "offline_lock", "is_visible",
    "is_course_list_visible", "is_course_state_visible",
    "is_participant_list_visible", "courses_in_participant_list", "is_cancelled",
    "is_archived", "lodge_field", "reserve_field", "course_room_field")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "shortname", "part_begin",
                     "part_end", "fee")

#: Fields of a track where courses can happen
COURSE_TRACK_FIELDS = ("id", "part_id", "title", "shortname", "num_choices",
                       "min_choices", "sortkey")

#: Fields of an extended attribute associated to an event entity
FIELD_DEFINITION_FIELDS = ("id", "event_id", "field_name", "kind",
                           "association", "entries")

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
    "real_persona_id", "amount_paid")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "status",
                            "lodgement_id", "is_reserve")

#: Fields of a registration which are specific for each course track
REGISTRATION_TRACK_FIELDS = ("registration_id", "track_id", "course_id",
                             "course_instructor")

#: Fields of a lodgement group
LODGEMENT_GROUP_FIELDS = ("id", "event_id", "moniker")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "moniker", "capacity", "reserve", "notes",
                    "group_id", "fields")

#: Fields of a mailing list entry (that is one mailinglist)
MAILINGLIST_FIELDS = (
    "id", "title", "address", "local_part", "domain", "description",
    "mod_policy", "notes", "attachment_policy", "ml_type",
    "subject_prefix", "maxsize", "is_active", "event_id", "registration_stati",
    "assembly_id")

#: Fields of an assembly
ASSEMBLY_FIELDS = ("id", "title", "description", "mail_address", "signup_end",
                   "is_active", "notes")

#: Fields of a ballot
BALLOT_FIELDS = (
    "id", "assembly_id", "title", "description", "vote_begin", "vote_end",
    "vote_extension_end", "extended", "use_bar", "quorum", "votes",
    "is_tallied", "notes")

#: Fields of an attachment in the assembly realm (attached either to an
#: assembly or a ballot)
ASSEMBLY_ATTACHMENT_FIELDS = ("id", "assembly_id", "ballot_id")

ASSEMBLY_ATTACHMENT_VERSION_FIELDS = ("attachment_id", "version", "title",
                                      "authors", "filename", "ctime", "dtime",
                                      "file_hash")

#: Fields of a semester
ORG_PERIOD_FIELDS = (
    "id", "billing_state", "billing_done", "ejection_state", "ejection_done",
    "ejection_count", "ejection_balance", "balance_state", "balance_done",
    "balance_trialmembers", "balance_total")

#: Fielsd of an expuls
EXPULS_PERIOD_FIELDS = ("id", "addresscheck_state", "addresscheck_done")

#: Fields of one direct debit permit
LASTSCHRIFT_FIELDS = (
    "id", "submitted_by", "persona_id", "amount", "iban",
    "account_owner", "account_address", "granted_at", "revoked_at", "notes")

#: Fields of one interaction on behalf of a direct debit permit
LASTSCHRIFT_TRANSACTION_FIELDS = (
    "id", "submitted_by", "lastschrift_id", "period_id", "status", "amount",
    "issued_at", "processed_at", "tally")

EPSILON = 10 ** (-6)  #:

#: Timestamp which lies in the future. Make a constant so we do not have to
#: hardcode the value otherwere
FUTURE_TIMESTAMP = datetime.datetime(9996, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
