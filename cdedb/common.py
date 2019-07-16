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

import psycopg2.extras
import pytz
import werkzeug.datastructures

_LOGGER = logging.getLogger(__name__)


class RequestState:
    """Container for request info. Besides this and db accesses the python
    code should be state-less. This data structure enables several
    convenient semi-magic behaviours (magic enough to be nice, but non-magic
    enough to not be non-nice).
    """

    def __init__(self, sessionkey, user, request, response, notifications,
                 mapadapter, requestargs, errors, values, lang, gettext,
                 ngettext, coders, begin, scriptkey, default_gettext=None,
                 default_ngettext=None):
        """
        :type sessionkey: str or None
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
        :type scriptkey: str or None
        :param scriptkey: Like a sessionkey, but for scripts. This is simply
          stored, so each frontend can take separate action.
        :type default_gettext: callable
        :param default_gettext: default translation function used to ensure
            stability across different locales
        :type default_ngettext: callable
        :param default_ngettext: default translation function used to ensure
            stability across different locales
        """
        self.ambience = {}
        self.sessionkey = sessionkey
        self.user = user
        self.request = request
        self.response = response
        self.notifications = notifications
        self.urls = mapadapter
        self.requestargs = requestargs
        self.errors = errors
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
        self.scriptkey = scriptkey
        # Visible version of the database connection
        self.conn = None
        # Private version of the database connection, only visible in the
        # backends (mediated by the ProxyShim)
        self._conn = None
        # Toggle to disable logging
        self.is_quiet = False
        # Is true, if the application detected an invalid (or no) CSRF token
        self.csrf_alert = False

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


class User:
    """Container for a persona."""

    def __init__(self, persona_id=None, roles=None, orga=None, moderator=None,
                 display_name="", given_names="", family_name="", username=""):
        """
        :type persona_id: int or None
        :type roles: {str}
        :param roles: python side privilege levels
        :type orga: {int} or None
        :param orga: Set of event ids for which this user is orga, only
          available in the event realm.
        :type moderator: {int} or None
        :param moderator: Set of mailing list ids for which this user is
          moderator, only available in the ml realm.
        :type display_name: str or None
        :type given_names: str or None
        :type family_name or None
        :type username: str or None
        """
        self.persona_id = persona_id
        self.roles = roles or {"anonymous"}
        self.orga = orga or set()
        self.moderator = moderator or set()
        self.username = username
        self.display_name = display_name
        self.given_names = given_names
        self.family_name = family_name


def do_singularization(fun):
    """Perform singularization on a function.

    This is the companion to the @singularize decorator.
    :type fun: callable
    :param fun: function with ``fun.singularization_hint`` attribute
    :rtype: callable
    :returns: singularized function
    """
    hint = fun.singularization_hint

    @functools.wraps(fun)
    def new_fun(rs, *args, **kwargs):
        if hint['singular_param_name'] in kwargs:
            param = kwargs.pop(hint['singular_param_name'])
            kwargs[hint['array_param_name']] = (param,)
        else:
            param = args[0]
            args = ((param,),) + args[1:]
        data = fun(rs, *args, **kwargs)
        if hint['returns_dict']:
            # raises KeyError if the requested thing does not exist
            return data[param]
        else:
            return data

    new_fun.__name__ = hint['singular_function_name']
    return new_fun


def do_batchification(fun):
    """Perform batchification on a function.

    This is the companion to the @batchify decorator.
    :type fun: callable
    :param fun: function with ``fun.batchification_hint`` attribute
    :rtype: callable
    :returns: batchified function
    """
    hint = fun.batchification_hint
    # Break cyclic import by importing here
    from cdedb.database.connection import Atomizer

    @functools.wraps(fun)
    def new_fun(rs, *args, **kwargs):
        ret = []
        with Atomizer(rs):
            if hint['array_param_name'] in kwargs:
                param = kwargs.pop(hint['array_param_name'])
                for datum in param:
                    new_kwargs = copy.deepcopy(kwargs)
                    new_kwargs[hint['singular_param_name']] = datum
                    ret.append(fun(rs, *args, **new_kwargs))
            else:
                param = args[0]
                for datum in param:
                    new_args = (datum,) + args[1:]
                    ret.append(fun(rs, *new_args, **kwargs))
        return ret

    new_fun.__name__ = hint['batch_function_name']
    return new_fun


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
                if hasattr(fun, "singularization_hint"):
                    hint = fun.singularization_hint
                    self._funs[hint['singular_function_name']] = self._wrapit(
                        do_singularization(fun))
                    setattr(backend, hint['singular_function_name'],
                            do_singularization(fun))
                if hasattr(fun, "batchification_hint"):
                    hint = fun.batchification_hint
                    self._funs[hint['batch_function_name']] = self._wrapit(
                        do_batchification(fun))
                    setattr(backend, hint['batch_function_name'],
                            do_batchification(fun))

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
    Exception for signalling missing privileges. This is thrown in the
    backend and caught in :py:mod:`cdedb.frontend.application`. We use a
    custom class so that we can distinguish it from other exceptions.
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


# TODO decide whether we sort by first or last name
def name_key(entry):
    """Create a sorting key associated to a persona dataset.

    This way we have a standardized sorting order for entries.

    :type entry: {str: object}
    :param entry: A dataset of a persona from the cde or event realm.
    :rtype: str
    """
    return (entry['family_name'] + " " + entry['given_names']).lower()


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
    :rtype: str
    :returns: The aggregated preference list.
    """
    if not votes:
        return '='.join(candidates)
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
    # Return the aggregate preference list in the same format as the input
    # votes are.
    return ">".join("=".join(level) for level in result)


#: Magic value of moniker of the ballot candidate representing the bar.
ASSEMBLY_BAR_MONIKER = "_bar_"


def unwrap(single_element_list, keys=False):
    """Remove one nesting layer (of lists, etc.).

    This is here to replace code like ``foo = bar[0]`` where bar is a
    list with a single element. This offers some more amenities: it
    works on dicts and performs validation.

    In case of an error (e.g. wrong number of elements) this raises an
    error.

    :type single_element_list: [obj]
    :type keys: bool
    :param keys: If a mapping is input, this toggles between returning
      the key or value.
    :rtype: object or None
    """
    if (not isinstance(single_element_list, collections.abc.Iterable)
            or len(single_element_list) != 1):
        raise RuntimeError(n_("Unable to unwrap!"))
    if isinstance(single_element_list, collections.abc.Mapping):
        if keys:
            single_element_list = single_element_list.keys()
        else:
            single_element_list = single_element_list.values()
    return next(i for i in single_element_list)


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

    :type date: datetime.datetime
    :type years: int
    :rtype: datetime.datetime
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


def mixed_existence_sorter(iterable):
    """Iterate over a set of indices in the relevant way.

    That is first over the non-negative indices in ascending order and
    then over the negative indices in descending order.

    This is the desired order if the UI offers the possibility to
    create multiple new entities enumerated by negative IDs.

    :type iterable: [int]
    """
    for i in sorted(iterable):
        if i >= 0:
            yield i
    for i in reversed(sorted(iterable)):
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


#: Version tag, so we know that we don't run out of sync with exported event
#: data. This has to be incremented whenever the event schema changes.
CDEDB_EXPORT_EVENT_VERSION = 4

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
    "address", "postal_code", "location", "country",
    "realm", "notes", "case_status", "reviewer")

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
                     "tempus")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "institution", "description", "shortname",
    "registration_start", "registration_soft_limit", "registration_hard_limit",
    "iban", "orga_address", "registration_text", "mail_text",
    "use_questionnaire", "notes", "offline_lock", "is_visible",
    "is_course_list_visible", "is_course_state_visible", "is_archived",
    "lodge_field", "reserve_field", "course_room_field")

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
    "real_persona_id")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "status",
                            "lodgement_id", "is_reserve")

#: Fields of a registration which are specific for each course track
REGISTRATION_TRACK_FIELDS = ("registration_id", "track_id", "course_id",
                             "course_instructor")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "moniker", "capacity", "reserve", "notes",
                    "fields")

#: Fields of a mailing list entry (that is one mailinglist)
MAILINGLIST_FIELDS = (
    "id", "title", "address", "description", "sub_policy", "mod_policy",
    "notes", "attachment_policy", "audience_policy", "subject_prefix",
    "maxsize", "is_active", "event_id", "registration_stati",
    "assembly_id")

#: Fields of a mailing list subscription
MAILINGLIST_SUBSCRIPTION_FIELDS = (
    "id", "mailinglist_id", "persona_id", "address", "is_subscribed",
    "is_override")

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
ASSEMBLY_ATTACHMENT_FIELDS = ("id", "assembly_id", "ballot_id", "title",
                              "filename")

#: Fields of a semester
ORG_PERIOD_FIELDS = ("id", "billing_state", "billing_done", "ejection_state",
                     "ejection_done", "balance_state", "balance_done")

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
