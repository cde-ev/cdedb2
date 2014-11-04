#!/usr/bin/env python3

"""Global utility functions."""

import cdedb.database.constants as const
import sys
import logging
import logging.handlers

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

def extract_realm(status):
    """
    :type status: int
    :rtype: str
    """
    if status is None:
        return None
    elif status in const.CDE_STATI:
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

def extract_global_privileges(db_privileges, status):
    """Take numerical raw values from the database and convert it into a
    set of semantic privilege levels.

    :type db_privileges: int or None
    :type status: :py:class:`cdedb.database.constants.PersonaStati` or None
    :rtype: {str}
    """
    if db_privileges is None or status is None:
        return {"anonymous",}
    ret = {"anonymous", "persona"}
    if status in const.MEMBER_STATI:
        ret.add("member")
    for privilege in const.PrivilegeBits:
        if db_privileges & privilege.value:
            ret.add(privilege.name)
    return ret


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
