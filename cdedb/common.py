#!/usr/bin/env python3

"""Global utility functions."""

import cdedb.database.constants as const
import abc
import datetime
import pytz
import sys
import logging
import logging.handlers
import collections
import collections.abc
import enum
import random
import string

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
    logger.debug("Configured logger {}.".format(name))
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

    :type dicts: [{obj: obj}]
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

class CommonUser(metaclass=abc.ABCMeta):
    """Abstract base class for container representing a persona."""
    def __init__(self, persona_id=None, roles=None, orga=None, moderator=None):
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
        """
        self.persona_id = persona_id
        self.roles = roles or {"anonymous"}
        self.orga = orga or set()
        self.moderator = moderator or set()

# TODO decide whether we sort by first or last name
def name_key(entry):
    """Create a sorting key associated to a persona dataset.

    This way we have a standardized sorting order for entries.

    :type entry: {str: obj}
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
        raise ValueError("Out of scope.")
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
        raise NotImplementedError("Not supported.")

def int_to_words(num, lang):
    """Convert an integer into a written representation.

    This is for the usage such as '2 apples' -> 'two apples'.

    :type num: int
    :type lang: str
    :param lang: Currently we only suppert 'de'.
    :rtype: str
    """
    if num < 0 or num > 999999:
        raise ValueError("Out of scope.")
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
        raise NotImplementedError("Not supported.")

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
        raise ValueError("Not in list.")
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
    :rtype: obj or None
    """
    if (not isinstance(single_element_list, collections.abc.Iterable)
            or len(single_element_list) != 1):
        raise RuntimeError("Unable to unwrap!")
    if isinstance(single_element_list, collections.abc.Mapping):
        if keys:
            single_element_list = single_element_list.keys()
        else:
            single_element_list = single_element_list.values()
    return next(i for i in single_element_list)

@enum.unique
class AgeClasses(enum.Enum):
    """Abstraction for encapsulating properties like legal status changing with
    age.

    If there is any need for additional detail in differentiating this
    can be centrally added here.
    """
    full = 0 #: at least 18 years old
    u18 = 1 #: between 16 and 18 years old
    u16 = 2 #: between 14 and 16 years old
    u14 = 3 #: less than 14 years old

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

def extract_roles(session_data):
    """FIXME

    NOTE: this also works on non-personas (i.e. dicts of is_* flags)

    :type db_privileges: int or None
    :type status: int or None
    :param status: will be converted to a
      :py:class:`cdedb.database.constants.PersonaStati`.
    :rtype: {str}
    """
    ret = {"anonymous"}
    if session_data['is_active']:
        ret.add("persona")
    else:
        return ret
    realms = {"cde", "event", "ml", "assembly"}
    for realm in realms:
        if session_data["is_{}_realm".format(realm)]:
            ret.add(realm)
            if session_data.get("is_{}_admin".format(realm)):
                ret.add("{}_admin".format(realm))
    if "cde" in ret:
        if session_data.get("is_core_admin"):
            ret.add("core_admin")
        if session_data.get("is_admin"):
            ret.add("admin")
        if session_data["is_member"]:
            ret.add("member")
            if session_data.get("is_searchable"):
                ret.add("searchable")
    ## Grant global admin all roles
    if "admin" in ret:
        for level in ("core", "cde", "event", "assembly", "ml"):
            ret.add("{}_admin".format(level))
        ret = ret | realms | {"member", "searchable"}
    return ret

def privilege_tier(roles):
    """FIXME"""
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
    "cloud_account", "notes")

#: Names of columns associated to a cde (formor)member
PERSONA_CDE_FIELDS = PERSONA_CORE_FIELDS + (
    "title", "name_supplement", "gender", "birthday", "telephone", "mobile",
    "address_supplement", "address", "postal_code", "location", "country",
    "birth_name", "address_supplement2", "address2", "postal_code2",
    "location2", "country2", "weblink", "specialisation", "affiliation",
    "timeline", "interests", "free_form", "balance", "decided_search",
    "trial_member", "bub_search", "foto")
    # FIXME foto was added

#: Names of columns associated to an event user. This should be a subset of
#: :py:data:`PERSONA_CDE_FIELDS` to facilitate upgrading of event users to
#: members.
PERSONA_EVENT_FIELDS = PERSONA_CORE_FIELDS + (
    "title", "name_supplement", "gender", "birthday", "telephone", "mobile",
    "address_supplement", "address", "postal_code", "location", "country")

#: Names of columns associated to a ml user.
PERSONA_ML_FIELDS = PERSONA_CORE_FIELDS

#: Names of columns associated to an assembly user.
PERSONA_ASSEMBLY_FIELDS = PERSONA_CORE_FIELDS

#: Names of all columns associated to an abstract persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_ALL_FIELDS = PERSONA_CDE_FIELDS

#: Fields of a persona creation case.
GENESIS_CASE_FIELDS = (
    "id", "ctime", "username", "given_names", "family_name",
    "realm", "notes", "case_status", "secret", "reviewer")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "organizer", "description", "tempus")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = (
    "id", "title", "organizer", "description", "shortname",
    "registration_start", "registration_soft_limit", "registration_hard_limit",
    "iban", "use_questionnaire", "notes", "offline_lock")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "part_begin", "part_end", "fee")

#: Fields of a concluded course
PAST_COURSE_FIELDS = ("id", "pevent_id", "title", "description")

#: Fields of a course associated to an event organized via the CdEDB
COURSE_FIELDS = ("id", "event_id", "title", "description", "nr", "shortname",
                 "instructors", "notes")

#: Fields of a registration to an event organized via the CdEDB
REGISTRATION_FIELDS = (
    "id", "persona_id", "event_id", "notes", "orga_notes", "payment",
    "parental_agreement", "mixed_lodging", "checkin", "foto_consent",
    "field_data", "real_persona_id")

#: Fields of a registration which are specific for each part of the event
REGISTRATION_PART_FIELDS = ("registration_id", "part_id", "course_id",
                            "status", "lodgement_id", "course_instructor")

#: Fields of a lodgement entry (one house/room)
LODGEMENT_FIELDS = ("id", "event_id", "moniker", "capacity", "reserve", "notes")

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
    "vote_extension_end", "extended", "bar", "quorum", "votes",
    "is_tallied", "notes")

#: Fields of an attachment in the assembly realm (attached either to an
#: assembly or a ballot)
ASSEMBLY_ATTACHMENT_FIELDS = ("id", "assembly_id", "ballot_id", "title",
                              "filename")

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
