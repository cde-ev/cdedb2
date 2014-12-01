#!/usr/bin/env python3

"""Global utility functions."""

import cdedb.database.constants as const
import abc
import sys
import logging
import logging.handlers
import collections

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

    :type dicts: [{obj : obj}]
    """
    assert(len(dicts) > 0)
    for adict in dicts[1:]:
        for key in adict:
            if key not in dicts[0]:
                dicts[0][key] = adict[key]

def extract_realm(status):
    """
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

class CommonUser(metaclass=abc.ABCMeta):
    """Abstract base class for container representing a persona."""
    def __init__(self, persona_id=None, roles={"anonymous"}, realm=None,
                 orga=None, moderator=None):
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
        self.roles = roles
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

#: A collection of the available privilege levels. More specifically the
#: keys of this dict specify the roles. The corresponding value is a set of
#: all roles which are upwards in the hierachy. Thus we have an encoded
#: graph, for a picture see :ref:`privileges`.
ALL_ROLES = {
    "anonymous" : {"anonymous", "persona", "core_admin",
                   "formermember", "member", "searchmember", "cde_admin",
                   "event_user", "event_admin",
                   "assembly_user", "assembly_admin",
                   "ml_user", "ml_admin",
                   "admin"},
    "persona" : {"persona", "core_admin",
                 "formermember", "member", "searchmember", "cde_admin",
                 "event_user", "event_admin",
                 "assembly_user", "assembly_admin",
                 "ml_user", "ml_admin",
                 "admin"},
    "core_admin" : {"admin"},
    "formermember" : {"formermember", "member", "searchmember", "cde_admin",
                      "admin"},
    "member" : {"member", "searchmember", "cde_admin",
                "admin"},
    "searchmember" : {"searchmember", "cde_admin",
                      "admin"},
    "cde_admin" : {"cde_admin",
                   "admin"},
    "event_user" : {"formermember", "member", "searchmember", "cde_admin",
                    "event_user", "event_admin",
                    "admin"},
    "event_admin" : {"event_admin",
                    "admin"},
    "assembly_user" : {"member", "searchmember", "cde_admin",
                       "assembly_user", "assembly_admin",
                       "admin"},
    "assembly_admin" : {"assembly_admin",
                        "admin"},
    "ml_user" : {"formermember", "member", "searchmember", "cde_admin",
                 "ml_user", "ml_admin",
                 "admin"},
    "ml_admin" : {"ml_admin",
                  "admin"},
    "admin" : {"admin"},
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

#: Names of columns associated to a persona, which are modifyable.
#: This does not include the ``password_hash`` for security reasons.
PERSONA_DATA_FIELDS_MOD = ("username", "display_name", "is_active", "status",
                           "db_privileges", "cloud_account")

#: names of all columns associated to a persona, regardless of modifyability
PERSONA_DATA_FIELDS = ("id",) + PERSONA_DATA_FIELDS_MOD

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

EPSILON = 10**(-6) #:
