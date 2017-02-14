#!/usr/bin/env python3

"""Global utility functions."""

import collections
import collections.abc
import copy
import datetime
import decimal
import enum
import functools
import inspect
import itertools
import json
import logging
import logging.handlers
import random
import string
import sys

import pytz
import werkzeug.datastructures

class RequestState:
    """Container for request info. Besides this and db accesses the python
    code should be state-less. This data structure enables several
    convenient semi-magic behaviours (magic enough to be nice, but non-magic
    enough to not be non-nice).
    """
    def __init__(self, sessionkey, user, request, response, notifications,
                 mapadapter, requestargs, urlmap, errors, values, lang, gettext,
                 ngettext, coders, begin):
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
        :type urlmap: :py:class:`werkzeug.routing.Map`
        :param urlmap: abstract URL information
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
        :param lang: translation function as in the gettext module
        :type coders: {str: callable}
        :param coders: Functions for encoding and decoding parameters primed
          with secrets. This is hacky, but sadly necessary.
        :type begin: datetime.datetime
        :param begin: time where we started to process the request
        """
        self.ambience = None
        self.sessionkey = sessionkey
        self.user = user
        self.request = request
        self.response = response
        self.notifications = notifications
        self.urls = mapadapter
        self.requestargs = requestargs
        self.urlmap = urlmap
        self.errors = errors
        if not isinstance(values, werkzeug.datastructures.MultiDict):
            values = werkzeug.datastructures.MultiDict(values)
        self.values = values
        self.lang = lang
        self.gettext = gettext
        self.ngettext = ngettext
        self._coders = coders
        self.begin = begin
        ## Visible version of the database connection
        self.conn = None
        ## Private version of the database connection, only visible in the
        ## backends (mediated by the ProxyShim)
        self._conn = None
        ## Toggle to disable logging
        self.is_quiet = False

    def notify(self, ntype, message, params=None):
        """Store a notification for later delivery to the user.

        :type ntype: str
        :param ntype: one of :py:data:`NOTIFICATION_TYPES`
        :type message: str
        """
        if ntype not in NOTIFICATION_TYPES:
            raise ValueError(_("Invalid notification type {t} found."),
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
        ## raises KeyError if the requested thing does not exist
        return data[param]
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
    ## Break cyclic import by importing here
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
                        ## Expose database connection for the backends
                        rs.conn = rs._conn
                    return fun(rs, *args, **kwargs)
                finally:
                    if not self._internal:
                        rs.conn = None
            else:
                raise PrivilegeError(_("Not in access list."))
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
    :type logfile_path: str
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
    file_handler = logging.FileHandler(logfile_path)
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

    :type dicts: [{object: object}]
    """
    assert(len(dicts) > 0)
    for adict in dicts[1:]:
        for key in adict:
            if key not in dicts[0]:
                dicts[0][key] = adict[key]

def random_ascii(length=12):
    """Create a random string of printable ASCII characters.

    :type length: int
    :param length: number of characters in the returned string
    :rtype: str
    """
    chars = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(chars) for _ in range(length))

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

# TODO decide whether we sort by first or last name
def name_key(entry):
    """Create a sorting key associated to a persona dataset.

    This way we have a standardized sorting order for entries.

    :type entry: {str: object}
    :param entry: A dataset of a persona from the cde or event realm.
    :rtype: str
    """
    return (entry['family_name'] + " " + entry['given_names']).lower()

def compute_checkdigit(value, isbn=False):
    """Map an integer to the checksum used for UI purposes.

    This checkdigit allows for error detection if somebody messes up a
    handwritten ID or such.

    Most of the time, the integer will be a persona id.

    :type value: int
    :type isbn: bool
    :param isbn: If True return a check digit according to the ISBN standard,
      otherwise we map the interval from 0 to 10 to the letters A to K.
    :rtype: str
    """
    digits = []
    tmp = value
    while tmp > 0:
        digits.append(tmp % 10)
        tmp = tmp // 10
    dsum = sum((i+2)*d for i, d in enumerate(digits))
    if isbn:
        return "0123456789X"[-dsum % 11]
    else:
        return "ABCDEFGHIJK"[-dsum % 11]

def lastschrift_reference(persona_id, lastschrift_id):
    """Return an identifier for usage with the bank.

    This is the so called 'Mandatsreferenz'.

    :type persona_id: int
    :type lastschrift_id: int
    :rtype: str
    """
    return "CDE-I25-{}-{}-{}-{}".format(
        persona_id, compute_checkdigit(persona_id, isbn=True), lastschrift_id,
        compute_checkdigit(lastschrift_id, isbn=True))

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
        raise ValueError(_("Out of supported scope."))
    digits = tuple((num // 10**i) % 10 for i in range(3))
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
                ret += atoms[num %100]
            return ret
        if digits[0]:
            ret += atoms[digits[0]]
        if digits[0] and digits[1]:
            ret += "und"
        if digits[1]:
            ret += tens[digits[1]]
        return ret
    else:
        raise NotImplementedError(_("Not supported."))

def int_to_words(num, lang):
    """Convert an integer into a written representation.

    This is for the usage such as '2 apples' -> 'two apples'.

    :type num: int
    :type lang: str
    :param lang: Currently we only suppert 'de'.
    :rtype: str
    """
    if num < 0 or num > 999999:
        raise ValueError(_("Out of supported scope."))
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
        raise NotImplementedError(_("Not supported."))

class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle the types that occur for us."""
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        elif isinstance(obj, decimal.Decimal):
            return str(obj)
        return super().default(self, obj)

def json_serialize(data):
    """Do beefed up JSON serialization.

    :type data: obj
    :rtype: str
    """
    return json.dumps(data, indent=4, cls=CustomJSONEncoder)

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
    ## First determine the strongst paths
    p = {(x, y): d[(x, y)] for x in candidates for y in candidates}
    for i in candidates:
        for j in candidates:
            if i == j:
                continue
            for k in candidates:
                if i == k or j == k:
                    continue
                p[(j, k)] = max(p[(j, k)], min(p[(j, i)], p[(i, k)]))
    ## Second determine winners
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
        raise ValueError(_("Not in list."))
    ## First we count the number of votes prefering x to y
    counts = {(x, y): 0 for x in candidates for y in candidates}
    for vote in split_votes:
        for x in candidates:
            for y in candidates:
                if _subindex(vote, x) < _subindex(vote, y):
                    counts[(x, y)] += 1
    ## Second we calculate a numeric link strength abstracting the problem
    ## into the realm of graphs with one vertex per candidate
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
        ## the margin strategy would be given by the following line
        ## return support - opposition
        if support > opposition:
            return totalvotes*support - opposition
        elif support == opposition:
            return 0
        else:
            return -1
    d = {(x, y): _strength(counts[(x, y)], counts[(y, x)], len(votes))
         for x in candidates for y in candidates}
    ## Third we execute the Schulze method by iteratively determining
    ## winners
    result = []
    while True:
        done = {x for level in result for x in level}
        ## avoid sets to preserve ordering
        remaining = tuple(c for c in candidates if c not in done)
        if not remaining:
            break
        winners = _schulze_winners(d, remaining)
        result.append(winners)
    ## Return the aggregate preference list in the same format as the input
    ## votes are.
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
        raise RuntimeError(_("Unable to unwrap!"))
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
    full = 1 #: at least 18 years old
    u18 = 2 #: between 16 and 18 years old
    u16 = 3 #: between 14 and 16 years old
    u14 = 4 #: less than 14 years old

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
        return date.replace(year=date.year-years)
    except ValueError:
        ## this can happen in only one situation: we tried to move a leap
        ## day into a year without leap
        assert(date.month == 2 and date.day == 29)
        return date.replace(year=date.year-years, day=28)

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
    create = 1 #: Create a new account with this data.
    skip = 2 #: Do nothing with this line.
    renew_trial = 3 #: Renew the trial membership of an existing account.
    update = 4 #: Update an existing account with this data.
    renew_and_update = 5 #: A combination of renew_trial and update.

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

@enum.unique
class CourseFilterPositions(enum.IntEnum):
    """Selection possibilities for the course assignment tool.

    We want to find registrations which have a specific course as choice
    or something else. Where exactly we search for the course is
    specified via this enum.
    """
    instructor = 1 #: Being a course instructor for the course in question.
    first_choice = 2 #:
    second_choice = 3 #:
    third_choice = 4 #:
    any_choice = 5 #:
    assigned = 6 #: Being in this course either as participant or as instructor.
    anywhere = 7 #:

@enum.unique
class SubscriptionStates(enum.IntEnum):
    """Relation to a mailing list.
    """
    unsubscribed = 1 #:
    subscribed = 2 #:
    requested = 10 #: A subscription request is waiting for moderation.

def _(x):
    """Alias of the identity for i18n."""
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

def diacritic_patterns(s):
    """Replace letters with a pattern matching expressions, so that
    ommitting diacritics in the query input is possible.

    This is intended for use with the sql SIMILAR TO clause or a python
    re module.

    :type s: str
    :rtype: str
    """
    ## if fragile special chars are present do nothing
    ## all special chars: '_%|*+?{}()[]'
    special_chars = '|*+?{}()[]'
    for char in special_chars:
        if char in s:
            return s
    ## some of the diacritics in use according to wikipedia
    umlaut_map = (
        ("ae", "(ae|[äæ])"),
        ("oe", "(oe|[öøœ])"),
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
    for normal, replacement in umlaut_map:
        s = s.replace(normal, replacement)
    return s

def extract_roles(session):
    """Associate some roles to a data set.

    The data contains the relevant portion of attributes from the
    core.personas table. We have some more logic than simply grabbing
    the flags from the dict like only allowing admin privileges in a
    realm if access to the realm is already granted.

    Note that this also works on non-personas (i.e. dicts of is_* flags).

    :type session: {str: object}
    :rtype: {str}
    """
    ret = {"anonymous"}
    if session['is_active']:
        ret.add("persona")
    else:
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
        if session.get("is_admin"):
            ret.add("admin")
        if session["is_member"]:
            ret.add("member")
            if session.get("is_searchable"):
                ret.add("searchable")
    ## Grant global admin all roles
    if "admin" in ret:
        for level in ("core", "cde", "event", "assembly", "ml"):
            ret.add("{}_admin".format(level))
        ret = ret | realms | {"member", "searchable"}
    return ret

def privilege_tier(roles):
    """Check admin privilege level.

    If a user has access to the passed realms, what kind of admin
    privileg does one need to edit the user?

    :type roles: {str}
    :rtype: {str}
    :returns: Admin roles that may edit this user.
    """
    relevant = roles & {"cde", "event", "ml", "assembly"}
    ret = {"core_admin", "admin"}
    if relevant == {"ml"}:
        return ret | {"ml_admin"}
    if "assembly" in relevant and relevant <= {"ml", "assembly"}:
        return ret | {"assembly_admin"}
    if "event" in relevant and relevant <= {"ml", "event"}:
        return ret | {"event_admin"}
    if "cde" in relevant and relevant <= {"ml", "event", "assembly", "cde"}:
        return ret | {"cde_admin"}
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
    'cloud_account': False,
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

#: Map of available privilege levels to those present in the SQL database
#: (where we have less differentiation for the sake of simplicity).
#:
#: This is an ordered dict, so that we can select the highest privilege
#: level.
DB_ROLE_MAPPING = collections.OrderedDict((
    ("admin", "cdb_admin"),
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



#: All columns deciding on the current status of a persona
PERSONA_STATUS_FIELDS = (
    "is_active", "is_admin", "is_core_admin", "is_cde_admin",
    "is_event_admin", "is_ml_admin", "is_assembly_admin", "is_cde_realm",
    "is_event_realm", "is_ml_realm", "is_assembly_realm", "is_member",
    "is_searchable", "is_archived")

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_CORE_FIELDS = PERSONA_STATUS_FIELDS + (
    "id", "username", "display_name", "family_name", "given_names",
    "cloud_account", "title", "name_supplement")

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
    "realm", "notes", "case_status", "secret", "reviewer")

#: Fields for institutions of events
INSTITUTION_FIELDS = ("id", "title", "moniker")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "shortname", "institution", "description",
                     "tempus")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "institution", "description", "shortname",
    "registration_start", "registration_soft_limit", "registration_hard_limit",
    "iban", "use_questionnaire", "notes", "offline_lock", "is_archived")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "part_begin", "part_end", "fee")

#: Fields of an extended attribute associated to an event entity
FIELD_DEFINITION_FIELDS = ("id", "event_id", "field_name", "kind",
                           "association", "entries")

#: Fields of a concluded course
PAST_COURSE_FIELDS = ("id", "pevent_id", "nr", "title", "description")

#: Fields of a course associated to an event organized via the CdEDB
COURSE_FIELDS = ("id", "event_id", "title", "description", "nr", "shortname",
                 "instructors", "max_size", "min_size", "notes", "fields")

#: Fields specifying in which part a course is available
COURSE_PART_FIELDS = ("course_id", "part_id", "is_active")

#: Fields of a registration to an event organized via the CdEDB
REGISTRATION_FIELDS = (
    "id", "persona_id", "event_id", "notes", "orga_notes", "payment",
    "parental_agreement", "mixed_lodging", "checkin", "foto_consent",
    "fields", "real_persona_id")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "course_id",
                            "status", "lodgement_id", "course_instructor")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "moniker", "capacity", "reserve", "notes",
                    "fields")

#: Fields of a mailing list entry (that is one mailinglist)
MAILINGLIST_FIELDS = (
    "id", "title", "address", "description", "sub_policy", "mod_policy",
    "notes", "attachment_policy", "audience_policy", "subject_prefix",
    "maxsize", "is_active", "gateway", "event_id", "registration_stati",
    "assembly_id")

#: Fields of an assembly
ASSEMBLY_FIELDS = ("id", "title", "description", "signup_end", "is_active",
                   "notes")

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
    "id", "submitted_by", "persona_id", "amount", "max_dsa", "iban",
    "account_owner", "account_address", "granted_at", "revoked_at", "notes")

#: Fields of one interaction on behalf of a direct debit permit
LASTSCHRIFT_TRANSACTION_FIELDS = (
    "id", "submitted_by", "lastschrift_id", "period_id", "status", "amount",
    "issued_at", "processed_at", "tally")

EPSILON = 10**(-6) #:

#: Timestamp which lies in the future. Make a constant so we do not have to
#: hardcode the value otherwere
FUTURE_TIMESTAMP = datetime.datetime(9996, 1, 1, 0, 0, 0, tzinfo=pytz.utc)
