#!/usr/bin/env python3

"""Global utility functions."""

import cdedb.database.constants as const
import abc
import sys
import logging
import logging.handlers
import collections
import collections.abc
import enum

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

def extract_realm(status):
    """Which realm does a persona belong to?

    Note how the conditions look, especially that they do not
    commute. The point being, that this symbols the interdependencies
    between backends. If we have a cycle in this dependency tree, we
    have a problem -- and we won't be able to make this function work
    properly too, so this is a nice indicator.

    :type status: int
    :rtype: str
    """
    if status is None:
        return None
    elif status in const.ALL_CDE_STATI:
        return "cde"
    elif status in const.EVENT_STATI:
        return "event"
    elif status in const.ASSEMBLY_STATI:
        return "assembly"
    elif status in const.ML_STATI:
        return "ml"
    else:
        raise ValueError("Invalid status {} found.".format(status))

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
    def __init__(self, persona_id=None, roles=None, realm=None, orga=None,
                 moderator=None):
        """
        :type persona_id: int or None
        :type roles: {str}
        :param roles: python side privilege levels
        :type realm: str or None
        :param realm: realm of origin, describing which component is
          responsible for handling the basic aspects of this user
        :type orga: {int} or None
        :param orga: Set of event ids for which this user is orga, only
          available in the event realm.
        :type moderator: {int} or None
        :param moderator: Set of mailing list ids for which this user is
          moderator, only available in the ml realm.
        """
        self.persona_id = persona_id
        self.roles = roles or {"anonymous"}
        self.realm = realm
        self.orga = orga or set()
        self.moderator = moderator or set()

    @property
    def is_persona(self):
        """Shorthand to determine user state."""
        return "persona" in self.roles

    @property
    def is_member(self):
        """Shorthand to determine user state."""
        return "member" in self.roles

    @property
    def is_searchable(self):
        """Shorthand to determine user state."""
        return "searchmember" in self.roles

def extract_roles(db_privileges, status):
    """Take numerical raw values from the database and convert it into a
    set of semantic privilege levels.

    :type db_privileges: int or None
    :type status: int or None
    :param status: will be converted to a
      :py:class:`cdedb.database.constants.PersonaStati`.
    :rtype: {str}
    """
    if db_privileges is None or status is None:
        return {"anonymous"}
    ret = {"anonymous", "persona"}
    status = const.PersonaStati(status)
    if status == const.PersonaStati.archived_member:
        raise RuntimeError("Impossible archived member found.")
    ret.add(status.name)
    for privilege in const.PrivilegeBits:
        if db_privileges & privilege.value:
            ret.add(privilege.name)
    ## ensure transitivity, that is that all dominated roles are present
    for possiblerole in ALL_ROLES:
        if ret & ALL_ROLES[possiblerole]:
            ret.add(possiblerole)
    return ret

# TODO decide whether we sort by first or last name
def name_key(entry):
    """Create a sorting key associated to a persona dataset.

    This way we have a standardized sorting order for entries.

    :type entry: {str: obj}
    :param entry: A dataset of a persona from the cde or event realm.
    :rtype: str
    """
    return (entry['family_name'] + " " + entry['given_names']).lower()

def compute_checkdigit(value):
    """Map a persona id (integer) to the checksum used for UI purposes.

    This checkdigit allows for error detection if somebody messes up a
    handwritten ID or such.

    :type value: int
    :rtype: str
    """
    digits = []
    tmp = value
    while tmp > 0:
        digits.append(tmp % 10)
        tmp = tmp // 10
    dsum = sum((i+1)*d for i, d in enumerate(digits))
    return chr(65 + (dsum % 11))

def unwrap(single_element_list, keys=False):
    """Remove one nesting layer (of lists, etc.).

    This is here to replace code like ``foo = bar[0]`` where bar is a
    list with a single element. This offers some more amenities: it
    works on dicts and performs validation.

    In case of an error (e.g. wrong number of elements) this returns
    ``None``.

    :type single_element_list: [obj]
    :type keys: bool
    :param keys: If a mapping is input, this toggles between returning
      the key or value.
    :rtype: obj or None
    """
    if not isinstance(single_element_list, collections.abc.Iterable):
        return None
    if len(single_element_list) != 1:
        return None
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

#: A collection of the available privilege levels. More specifically the
#: keys of this dict specify the roles. The corresponding value is a set of
#: all roles which are upwards in the hierachy. Thus we have an encoded
#: graph, for a picture see :ref:`privileges`.
ALL_ROLES = {
    "anonymous": {"anonymous", "persona", "core_admin",
                  "formermember", "member", "searchmember", "cde_admin",
                  "event_user", "event_admin",
                  "assembly_user", "assembly_admin",
                  "ml_user", "ml_admin", "ml_script",
                  "admin"},
    "persona": {"persona", "core_admin",
                "formermember", "member", "searchmember", "cde_admin",
                "event_user", "event_admin",
                "assembly_user", "assembly_admin",
                "ml_user", "ml_admin",
                "admin"},
    "core_admin": {"core_admin",
                   "admin"},
    "formermember": {"formermember", "member", "searchmember", "cde_admin",
                     "admin"},
    "member": {"member", "searchmember", "cde_admin",
               "admin"},
    "searchmember": {"searchmember", "cde_admin",
                     "admin"},
    "cde_admin": {"cde_admin",
                  "admin"},
    "event_user": {"formermember", "member", "searchmember", "cde_admin",
                   "event_user", "event_admin",
                   "admin"},
    "event_admin": {"event_admin",
                    "admin"},
    "assembly_user": {"member", "searchmember", "cde_admin",
                      "assembly_user", "assembly_admin",
                      "admin"},
    "assembly_admin": {"assembly_admin",
                       "admin"},
    "ml_user": {"formermember", "member", "searchmember", "cde_admin",
                "event_user", "event_admin",
                "assembly_user", "assembly_admin",
                "ml_user", "ml_admin",
                "admin"},
    "ml_admin": {"ml_admin",
                 "admin"},
    "ml_script": {"admin"},
    "admin": {"admin"},
}

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

    ("searchmember", "cdb_member"),
    ("member", "cdb_member"),
    ("formermember", "cdb_member"),
    ("assembly_user", "cdb_member"),

    ("event_user", "cdb_persona"),
    ("ml_user", "cdb_persona"),
    ("persona", "cdb_persona"),

    ("anonymous", "cdb_anonymous"),
))

#: Names of all columns associated to a persona.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_DATA_FIELDS = ("id", "username", "display_name", "is_active", "status",
                       "db_privileges", "cloud_account")

#: names of columns associated to a cde member (in addition to those which
#: exist for every persona)
MEMBER_DATA_FIELDS = (
    "family_name", "given_names", "title", "name_supplement", "gender",
    "birthday", "telephone", "mobile", "address_supplement", "address",
    "postal_code", "location", "country", "notes", "birth_name",
    "address_supplement2", "address2", "postal_code2", "location2",
    "country2", "weblink", "specialisation", "affiliation", "timeline",
    "interests", "free_form", "balance", "decided_search", "trial_member",
    "bub_search")

#: Names of columns associated to an event user (in addition to those which
#: exist for every persona). This should be a subset of
#: :py:data:`MEMBER_DATA_FIELDS` to facilitate upgrading of event users to
#: memebers.
EVENT_USER_DATA_FIELDS = (
    "family_name", "given_names", "title", "name_supplement", "gender",
    "birthday", "telephone", "mobile", "address_supplement", "address",
    "postal_code", "location", "country", "notes")

#: Names of columns associated to an ml user (in addition to those which
#: exist for every persona).
ML_USER_DATA_FIELDS = ("family_name", "given_names", "notes")

#: Fields of a persona creation case.
GENESIS_CASE_FIELDS = (
    "id", "ctime", "username", "full_name", "persona_status", "notes",
    "case_status", "secret", "reviewer")

#: Fields of a concluded event
PAST_EVENT_FIELDS = ("id", "title", "organizer", "description")

#: Fields of an event organized via the CdEDB
EVENT_FIELDS = PAST_EVENT_FIELDS + (
    "shortname", "registration_start", "registration_soft_limit",
    "registration_hard_limit", "iban", "use_questionnaire", "notes",
    "offline_lock")

#: Fields of an event part organized via CdEDB
EVENT_PART_FIELDS = ("id", "event_id", "title", "part_begin", "part_end", "fee")

#: Fields of a concluded course
PAST_COURSE_FIELDS = ("id", "event_id", "title", "description")

#: Fields of a course associated to an event organized via the CdEDB
COURSE_FIELDS = PAST_COURSE_FIELDS + ("nr", "shortname", "instructors", "notes")

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
    "id", "title", "address", "sub_policy", "mod_policy", "notes",
    "attachement_policy", "audience", "subject_prefix", "maxsize",
    "is_active", "gateway", "event_id", "registration_stati", "assembly_id")

EPSILON = 10**(-6) #:
