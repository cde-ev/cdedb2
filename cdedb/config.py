#!/usr/bin/env python3

"""This provides config objects for the CdEDB, that is: default values and
a way to override them. Any hardcoded values should be found in
here. Each config object takes into account the default values found in
here, the site specific global overrides in
:py:mod:`cdedb.localconfig` and with exception of
:py:class:`BasicConfig` an invocation specific override.
"""

import datetime
import decimal
import importlib.machinery
import logging
import os.path
import subprocess
import uuid

import pytz

from cdedb.query import Query, QUERY_SPECS, QueryOperators
from cdedb.common import deduct_years, now

_LOGGER = logging.getLogger(__name__)

_currentpath = os.path.dirname(os.path.abspath(__file__))
if not _currentpath.startswith('/') or not _currentpath.endswith('/cdedb'):
    raise RuntimeError("Failed to locate repository")
_repopath = _currentpath[:-6]
_git_commit = subprocess.check_output(
    ("git", "rev-parse", "HEAD"), cwd=_repopath).decode().strip()

#: defaults for :py:class:`BasicConfig`
_BASIC_DEFAULTS = {
    ## True for development instances
    "CDEDB_DEV": False,
    ## Logging level for CdEDBs own log files
    "LOG_LEVEL": logging.INFO,
    ## Logging level for syslog
    "SYSLOG_LEVEL": logging.WARNING,
    ## Logging level for stdout
    "CONSOLE_LOG_LEVEL": None,
    ## Global log for messages unrelated to specific components
    "GLOBAL_LOG": "/tmp/cdedb.log",
    ## file system path to this repository
    "REPOSITORY_PATH": _repopath,
    ## hash id of the current HEAD/running version
    "GIT_COMMIT": _git_commit,
    ## relative path to config file with settings for the test suite
    "TESTCONFIG_PATH": "test/localconfig.py",
    ## port on which the database listens, preferably a pooler like pgbouncer
    "DB_PORT": 6432,
    ## default timezone for input and output
    "DEFAULT_TIMEZONE": pytz.timezone('CET'),
    ## path to log file for recording performance information during test runs
    "TIMING_LOG": "/tmp/cdedb-timing.log",
}

#: defaults for :py:class:`Config`
_DEFAULTS = {
    ###
    ### Global stuff
    ###

    ## name of database to use
    "CDB_DATABASE_NAME": "cdb",

    ## True for offline versions running on academies
    "CDEDB_OFFLINE_DEPLOYMENT": False,

    ## If True only core admins are granted access
    "LOCKDOWN": False,

    ## location of ldap server
    "LDAP_URL": "ldap://localhost",
    ## name of ldap unit (i.e. subtree) to use
    "LDAP_UNIT_NAME": "ou=personas,dc=cde-ev,dc=de",
    ## name of ldap user to use
    "LDAP_USER": "cn=root,dc=cde-ev,dc=de",

    ## place for uploaded data
    "STORAGE_DIR": "/var/lib/cdedb/",

    ###
    ### Frontend stuff
    ###

    ## log for frontend issues
    "FRONTEND_LOG": "/tmp/cdedb-frontend.log",
    ## timeout for protected url parameters to prevent replay
    "ONLINE_PARAMETER_TIMEOUT": datetime.timedelta(seconds=120),
    ## email is a slower medium, so this has a longer timeout
    "EMAIL_PARAMETER_TIMEOUT": datetime.timedelta(days=1),
    ## maximum length of rationale for requesting an account
    "MAX_RATIONALE": 500,
    ## minimal number of input characters to start a search for personas
    ## fitting an intelligent input field
    "NUM_PREVIEW_CHARS": 3,
    ## maximum length of personas presented for selection in an intelligent
    ## input field
    "NUM_PREVIEW_PERSONAS": 42,

    ###
    ### email stuff
    ###

    ## email for administrative notifications
    "MANAGEMENT_ADDRESS": "verwaltung@cde-ev.de",
    ## default return address for mails
    "DEFAULT_REPLY_TO": "verwaltung@cde-ev.de",
    ## default return path for bounced mail
    "DEFAULT_RETURN_PATH": "bounces@cde-ev.de",
    ## default sender address for mails
    "DEFAULT_SENDER": '"CdE-Mitgliederverwaltung" <verwaltung@cde-ev.de>',
    ## domain for emails (determines message id)
    "MAIL_DOMAIN": "db.cde-ev.de",
    ## host to use for sending emails
    "MAIL_HOST": "localhost",

    ## email for event account requests
    "EVENT_ADMIN_ADDRESS": "event-admins@cde-ev.de",
    ## email for ml account requests
    "ML_ADMIN_ADDRESS": "ml-admins@cde-ev.de",

    ## logs
    "CORE_FRONTEND_LOG": "/tmp/cdedb-frontend-core.log",
    "CDE_FRONTEND_LOG": "/tmp/cdedb-frontend-cde.log",
    "EVENT_FRONTEND_LOG": "/tmp/cdedb-frontend-event.log",
    "ML_FRONTEND_LOG": "/tmp/cdedb-frontend-ml.log",
    "ASSEMBLY_FRONTEND_LOG": "/tmp/cdedb-frontend-assembly.log",

    ###
    ### Backend stuff
    ###

    ## log for backend issues
    "BACKEND_LOG": "/tmp/cdedb-backend.log",

    ### Core stuff

    ## log
    "CORE_BACKEND_LOG": "/tmp/cdedb-backend-core.log",

    ### Session stuff

    ## log
    "SESSION_BACKEND_LOG": "/tmp/cdedb-backend-session.log",

    ## session parameters
    "SESSION_TIMEOUT": datetime.timedelta(days=2),
    "SESSION_LIFESPAN": datetime.timedelta(days=7),

    ### CdE stuff

    ## log
    "CDE_BACKEND_LOG": "/tmp/cdedb-backend-cde.log",

    ## maximal number of data sets a normal user is allowed to view per day
    "MAX_QUERIES_PER_DAY": 50,
    ## maximal number of results for a member search
    "MAX_QUERY_RESULTS": 50,
    ## amount deducted from balance each period (semester)
    "MEMBERSHIP_FEE": decimal.Decimal('2.50'),
    ## probably always 1 or 2
    "PERIODS_PER_YEAR": 2,

    ## Name of the organization where the SEPA transaction originated
    "SEPA_SENDER_NAME": "CdE e.V.",
    ## Address of the originating organization
    ## The actual address consists of multiple lines
    "SEPA_SENDER_ADDRESS": ("Musterstrasse 123", "00000 Teststadt"),
    "SEPA_SENDER_COUNTRY": "DE",
    ## Bank details of the originator
    "SEPA_SENDER_IBAN": "DE87200500001234567890",
    ## "Gläubiger-ID" for direct debit transfers
    "SEPA_GLAEUBIGERID": "DE00ZZZ00099999999",
    ## Date at which SEPA was introduced
    "SEPA_INITIALISATION_DATE": datetime.date(2013, 7, 30),
    ## Date after which SEPA was used exclusively
    "SEPA_CUTOFF_DATE": datetime.date(2013, 10, 14),
    ## Timespan to wait between issuing of SEPA order and fulfillment
    "SEPA_PAYMENT_OFFSET": datetime.timedelta(days=17),
    ## processing fee we incur if a transaction is rolled back
    "SEPA_ROLLBACK_FEE": decimal.Decimal('4.50'),

    ### event stuff

    ## log
    "EVENT_BACKEND_LOG": "/tmp/cdedb-backend-event.log",

    ### past event stuff

    ## log
    "PAST_EVENT_BACKEND_LOG": "/tmp/cdedb-backend-past-event.log",

    ### ml stuff

    ## log
    "ML_BACKEND_LOG": "/tmp/cdedb-backend-ml.log",

    ### assembly stuff

    ## log
    "ASSEMBLY_BACKEND_LOG": "/tmp/cdedb-backend-assembly.log",

    ###
    ### Query stuff
    ###

    ## dict where the values are dicts mapping titles to queries for "speed
    ## dialing"
    "DEFAULT_QUERIES": {
        "qview_cde_user": {
            "trial members": Query(
                "qview_cde_user", QUERY_SPECS['qview_cde_user'],
                ("personas.id", "given_names", "family_name"),
                (("trial_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True)),),
        },
        "qview_archived_persona": {
            "with notes": Query(
                "qview_archived_persona",
                QUERY_SPECS['qview_archived_persona'],
                ("personas.id", "given_names", "family_name", "birth_name"),
                (("notes", QueryOperators.nonempty, None),),
                (("family_name", True), ("given_names", True)),),
        },
        "qview_event_user": {
            "minors": Query(
                "qview_event_user", QUERY_SPECS['qview_event_user'],
                ("persona.persona_id", "given_names", "family_name",
                 "birthday"),
                (("birthday", QueryOperators.greater,
                  deduct_years(now().date(), 18)),),
                (("birthday", True), ("family_name", True),
                 ("given_names", True)),),
        },
        "qview_registration": {
            ## none since they need additional input, will be created on the fly
        },
        "qview_core_user": {
            "all": Query(
                "qview_persona", QUERY_SPECS['qview_core_user'],
                ("personas.id", "given_names", "family_name"),
                tuple(),
                (("personas.id", True),),)
        },
        "qview_persona": {
            "all": Query(
                "qview_persona", QUERY_SPECS['qview_persona'],
                ("id", "given_names", "family_name"),
                tuple(),
                tuple(),)
        },
    },
}

#: defaults for :py:class:`SecretsConfig`
_SECRECTS_DEFAULTS = {
    ## database users
    "CDB_DATABASE_ROLES": {
        "cdb_anonymous": "012345678901234567890123456789",
        "cdb_persona": "abcdefghijklmnopqrstuvwxyzabcd",
        "cdb_member": "zyxwvutsrqponmlkjihgfedcbazyxw",
        "cdb_admin": "9876543210abcdefghijklmnopqrst"
        },

    ## salting value used for verifying sensitve url parameters
    "URL_PARAMETER_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",

    ## salting value used for verifying password reset authorization
    "RESET_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",

    ## salting value used for verifying tokens for username changes
    "USERNAME_CHANGE_TOKEN_SALT": "kaoslrcekhvx2387krcoekd983xRKCh309xKX",

    ## password of ldap user above
    "LDAP_PASSWORD": "s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0",

    ## key to use by mailing list software for authentification
    "ML_SCRIPT_KEY": "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",
}

class BasicConfig:
    """Global configuration for elementary options.

    This is the global configuration which is the same for all
    processes. This is to be used when no invocation context is
    available (or it is infeasible to get at). There is no way to
    override the values on invocation, so the amount of values handled
    by this should be as small as possible.
    """
    def __init__(self):
        try:
            import cdedb.localconfig as primaryconf
        except ImportError:
            primaryconf = None
        for param in _BASIC_DEFAULTS:
            try:
                setattr(self, param, getattr(primaryconf, param))
            except AttributeError:
                setattr(self, param, _BASIC_DEFAULTS[param])

class Config(BasicConfig):
    """Main configuration.

    This provides the primary configuration. It takes a path for
    allowing overrides on each invocation. This does not enable
    overriding the values inherited from :py:class:`BasicConfig`.
    """
    def __init__(self, configpath):
        """
        :type configpath: str
        :param configpath: path to file with overrides
        """
        super().__init__()
        _LOGGER.debug("Initialising Config with path {}".format(configpath))
        self._configpath = configpath
        if configpath:
            module_id = str(uuid.uuid4()) ## otherwise importlib caches wrongly
            loader = importlib.machinery.SourceFileLoader(module_id, configpath)
            primaryconf = loader.load_module(module_id)
        else:
            primaryconf = None
        try:
            import cdedb.localconfig as secondaryconf
        except ImportError:
            secondaryconf = None
        for param in _DEFAULTS:
            try:
                setattr(self, param, getattr(primaryconf, param))
            except AttributeError:
                try:
                    setattr(self, param, getattr(secondaryconf, param))
                except AttributeError:
                    setattr(self, param, _DEFAULTS[param])
        for param in _BASIC_DEFAULTS:
            try:
                getattr(primaryconf, param)
                _LOGGER.info("Ignored basic config entry {} in {}.".format(
                    param, configpath))
            except AttributeError:
                pass

class SecretsConfig:
    """Container for secrets (i.e. passwords).

    This works like :py:class:`Config`, but is used for secrets. Thus
    the invocation specific overrides are imperative since passwords
    should not be left in a globally accessible spot.
    """
    def __init__(self, configpath):
        _LOGGER.debug("Initialising SecretsConfig with path {}".format(
            configpath))
        if configpath:
            module_id = str(uuid.uuid4()) ## otherwise importlib caches wrongly
            loader = importlib.machinery.SourceFileLoader(module_id, configpath)
            primaryconf = loader.load_module(module_id)
        else:
            primaryconf = None
        try:
            import cdedb.localconfig as secondaryconf
        except ImportError:
            secondaryconf = None
        for param in _SECRECTS_DEFAULTS:
            try:
                setattr(self, param, getattr(primaryconf, param))
            except AttributeError:
                try:
                    setattr(self, param, getattr(secondaryconf, param))
                except AttributeError:
                    setattr(self, param, _SECRECTS_DEFAULTS[param])
