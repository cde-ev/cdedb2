#!/usr/bin/env python3

"""This provides config objects for the CdEDB, that is: default values and
a way to override them. Any hardcoded values should be found in
here. Each config object takes into account the default values found in
here, the site specific global overrides in
:py:mod:`cdedb.localconfig` and with exception of
:py:class:`BasicConfig` an invocation specific override.
"""

import collections
import collections.abc
import datetime
import decimal
import importlib.util
import logging
import pathlib
import subprocess
import uuid

import pytz

from cdedb.query import Query, QUERY_SPECS, QueryOperators
from cdedb.common import n_, deduct_years, now
import cdedb.database.constants as const

_LOGGER = logging.getLogger(__name__)

_currentpath = pathlib.Path(__file__).resolve().parent
if _currentpath.parts[0] != '/' or _currentpath.parts[-1] != 'cdedb':
    raise RuntimeError(n_("Failed to locate repository"))
_repopath = _currentpath.parent
_git_commit = subprocess.check_output(
    ("git", "rev-parse", "HEAD"), cwd=str(_repopath)).decode().strip()

#: defaults for :py:class:`BasicConfig`
_BASIC_DEFAULTS = {
    # Logging level for CdEDBs own log files
    "LOG_LEVEL": logging.INFO,
    # Logging level for syslog
    "SYSLOG_LEVEL": logging.WARNING,
    # Logging level for stdout
    "CONSOLE_LOG_LEVEL": None,
    # Global log for messages unrelated to specific components
    "GLOBAL_LOG": pathlib.Path("/tmp/cdedb.log"),
    # file system path to this repository
    "REPOSITORY_PATH": _repopath,
    # relative path to config file with settings for the test suite
    "TESTCONFIG_PATH": pathlib.Path("test/localconfig.py"),
    # default timezone for input and output
    "DEFAULT_TIMEZONE": pytz.timezone('CET'),
    # path to log file for recording performance information during test runs
    "TIMING_LOG": pathlib.Path("/tmp/cdedb-timing.log"),
}


def generate_event_registration_default_queries(event, spec):
    """
    Generate default queries for registration_query.

    Some of these contain dynamic information about the event's Parts,
    Tracks, etc.

    :param event: The Event for which to generate the queries
    :type event:
    :param spec: The Query Spec, dynamically generated for the event
    :type spec:
    :return: Dict of default queries
    """
    default_sort = (("persona.family_name", True),
                    ("persona.given_names", True),
                    ("reg.id", True))

    all_part_stati_column = ",".join(
        "part{0}.status".format(part_id) for part_id in event['parts'])

    dokuteam_course_fields_of_interest = [
        "persona.given_names", "persona.family_name", "persona.username"]
    for part_id in event['parts']:
        dokuteam_course_fields_of_interest.append(
            "part{}.status".format(part_id))
    for track_id in event['tracks']:
        dokuteam_course_fields_of_interest.append(
            "course{}.id".format(track_id))

    dokuteam_address_fields_of_interest = [
        "persona.given_names", "persona.family_name", "persona.address",
        "persona.address_supplement", "persona.postal_code", "persona.location",
        "persona.country"]

    queries = {
        n_("00_query_event_registration_all"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name"),
            tuple(),
            (("reg.id", True),)),
        n_("02_query_event_registration_orgas"): Query(
          "qview_registration", spec,
            ("persona.given_names", "persona.family_name"),
            (("persona.id", QueryOperators.oneof, event['orgas']),),
             default_sort),
        n_("10_query_event_registration_not_paid"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name"),
            (("reg.payment", QueryOperators.empty, None),),
            default_sort),
        n_("12_query_event_registration_paid"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "reg.payment"),
            (("reg.payment", QueryOperators.nonempty, None),),
            (("reg.payment", False), ("persona.family_name", True),
             ("persona.given_names", True),)),
        n_("14_query_event_registration_participants"): Query(
            "qview_registration", spec,
            all_part_stati_column.split(",") +
            ["persona.given_names", "persona.family_name"],
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),),
            default_sort),
        n_("14_query_event_registration_waitlist"): Query(
            "qview_registration", spec,
            all_part_stati_column.split(",") +
            ["persona.given_names", "persona.family_name",
             "ctime.creation_time", "reg.payment"],
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.waitlist.value),),
            (("ctime.creation_time", True),)),
        n_("20_query_event_registration_non_members"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name"),
            (("persona.is_member", QueryOperators.equal, False),),
            default_sort),
        n_("30_query_event_registration_orga_notes"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "reg.orga_notes"),
            (("reg.orga_notes", QueryOperators.nonempty, None),),
            default_sort),
        n_("40_query_event_registration_u18"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 18)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True),)),
        n_("42_query_event_registration_u16"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 16)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("44_query_event_registration_u14"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 14)),),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("50_query_event_registration_minors_no_consent"): Query(
            "qview_registration", spec,
            ("persona.given_names", "persona.family_name", "persona.birthday"),
            (("persona.birthday", QueryOperators.greater,
              deduct_years(event['begin'], 18)),
             ("reg.parental_agreement", QueryOperators.equal, False)),
            (("persona.birthday", True), ("persona.family_name", True),
             ("persona.given_names", True))),
        n_("60_query_dokuteam_course_export"): Query(
            "qview_registration", spec, dokuteam_course_fields_of_interest,
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),),
            default_sort),
        n_("62_query_dokuteam_address_export"): Query(
            "qview_registration", spec, dokuteam_address_fields_of_interest,
            ((all_part_stati_column, QueryOperators.equal,
              const.RegistrationPartStati.participant.value),),
            default_sort),
    }

    return queries


#: defaults for :py:class:`Config`
_DEFAULTS = {
    ################
    # Global stuff #
    ################

    # name of database to use
    "CDB_DATABASE_NAME": "cdb",

    # port on which the database listens, preferably a pooler like pgbouncer
    "DB_PORT": 6432,

    # True for offline versions running on academies
    "CDEDB_OFFLINE_DEPLOYMENT": False,

    # If True only core admins are granted access
    "LOCKDOWN": False,

    # True for development instances
    "CDEDB_DEV": False,

    # True when running within unit test environment
    "CDEDB_TEST": False,

    # place for uploaded data
    "STORAGE_DIR": pathlib.Path("/var/lib/cdedb/"),

    # hash id of the current HEAD/running version
    "GIT_COMMIT": _git_commit,

    ##################
    # Frontend stuff #
    ##################

    # log for frontend issues
    "FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend.log"),
    # timeout for protected url parameters to prevent replay
    "PARAMETER_TIMEOUT": datetime.timedelta(hours=1),
    # timeout for protected parameters, that are not security related
    "UNCRITICAL_PARAMETER_TIMEOUT": datetime.timedelta(days=1),
    # timeoue for parameters, in unsuspected emails (triggered by another user)
    "EMAIL_PARAMETER_TIMEOUT": datetime.timedelta(days=2),
    # maximum length of rationale for requesting an account
    "MAX_RATIONALE": 500,
    # minimal number of input characters to start a search for personas
    # fitting an intelligent input field
    "NUM_PREVIEW_CHARS": 3,
    # maximum length of personas presented via select persona API for selection
    # in an intelligent input field for core admins
    "NUM_PREVIEW_PERSONAS_CORE_ADMIN": 12,
    # maximum length of personas presented via select persona API for any other
    # user
    "NUM_PREVIEW_PERSONAS": 3,
    # Available languages
    "I18N_LANGUAGES": ("de", "en"),

    ###############
    # email stuff #
    ###############

    # email for administrative notifications
    "MANAGEMENT_ADDRESS": "verwaltung@cde-ev.de",
    # default return address for mails
    "DEFAULT_REPLY_TO": "verwaltung@cde-ev.de",
    # default return path for bounced mail
    "DEFAULT_RETURN_PATH": "bounces@cde-ev.de",
    # default sender address for mails
    "DEFAULT_SENDER": '"CdE-Datenbank" <datenbank@cde-ev.de>',
    # domain for emails (determines message id)
    "MAIL_DOMAIN": "db.cde-ev.de",
    # host to use for sending emails
    "MAIL_HOST": "localhost",

    # email for cde account requests
    "CDE_ADMIN_ADDRESS": "cde-admins@cde-ev.de",
    # email for event account requests
    "EVENT_ADMIN_ADDRESS": "event-admins@cde-ev.de",
    # email for ml account requests
    "ML_ADMIN_ADDRESS": "ml-admins@cde-ev.de",
    # email for replies to assembly mails
    "ASSEMBLY_ADMIN_ADDRESS": "vorstand@cde-ev.de",

    # email for privilege changes
    "META_ADMIN_ADDRESS": "admin@lists.cde-ev.de",

    # email for ballot tallies
    "BALLOT_TALLY_ADDRESS": "wahlbekanntmachung@lists.cde-ev.de",

    # mailman REST API host
    "MAILMAN_HOST": "localhost:8001",
    # mailman REST API user
    "MAILMAN_USER": "restadmin",
    # user for mailman to retrieve templates
    "MAILMAN_BASIC_AUTH_USER": "mailman",

    # logs
    "CORE_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-core.log"),
    "CDE_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-cde.log"),
    "EVENT_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-event.log"),
    "ML_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-ml.log"),
    "ASSEMBLY_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-assembly.log"),
    "CRON_FRONTEND_LOG": pathlib.Path("/tmp/cdedb-frontend-cron.log"),

    #################
    # Backend stuff #
    #################

    # log for backend issues
    "BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend.log"),

    #
    # Core stuff
    #

    # log
    "CORE_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-core.log"),

    #
    # Session stuff
    #

    # log
    "SESSION_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-session.log"),

    # session parameters
    "SESSION_TIMEOUT": datetime.timedelta(days=2),
    "SESSION_LIFESPAN": datetime.timedelta(days=7),

    #
    # CdE stuff
    #

    # log
    "CDE_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-cde.log"),

    # maximal number of data sets a normal user is allowed to view per day
    "QUOTA_VIEWS_PER_DAY": 42,
    # maximal number of results for a member search
    "MAX_MEMBER_SEARCH_RESULTS": 200,
    # amount deducted from balance each period (semester)
    "MEMBERSHIP_FEE": decimal.Decimal('2.50'),
    # probably always 1 or 2
    "PERIODS_PER_YEAR": 2,

    # Name of the organization where the SEPA transaction originated
    "SEPA_SENDER_NAME": "CdE e.V.",
    # Address of the originating organization
    # The actual address consists of multiple lines
    "SEPA_SENDER_ADDRESS": ("Musterstrasse 123", "00000 Teststadt"),
    "SEPA_SENDER_COUNTRY": "DE",
    # Bank details of the originator
    "SEPA_SENDER_IBAN": "DE87200500001234567890",
    # "Gläubiger-ID" for direct debit transfers
    "SEPA_GLAEUBIGERID": "DE00ZZZ00099999999",
    # Date at which SEPA was introduced
    "SEPA_INITIALISATION_DATE": datetime.date(2013, 7, 30),
    # Date after which SEPA was used exclusively
    "SEPA_CUTOFF_DATE": datetime.date(2013, 10, 14),
    # Timespan to wait between issuing of SEPA order and fulfillment
    "SEPA_PAYMENT_OFFSET": datetime.timedelta(days=17),
    # processing fee we incur if a transaction is rolled back
    "SEPA_ROLLBACK_FEE": decimal.Decimal('4.50'),

    #
    # event stuff
    #

    # log
    "EVENT_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-event.log"),
    # Bank accounts. First is shown to participants,
    # second is a web label for orgas
    "EVENT_BANK_ACCOUNTS": (
        ("DE96370205000008068901", "DE96370205000008068901"),
    ),
    # Rate limit for orgas adding persons to their event
    # number of persons per day
    "ORGA_ADD_LIMIT": 10,

    #
    # past event stuff
    #

    # log
    "PAST_EVENT_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-past-event.log"),

    #
    # ml stuff
    #

    # log
    "ML_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-ml.log"),

    #
    # assembly stuff
    #

    # log
    "ASSEMBLY_BACKEND_LOG": pathlib.Path("/tmp/cdedb-backend-assembly.log"),

    ###############
    # Query stuff #
    ###############

    # dict where the values are dicts mapping titles to queries for "speed
    # dialing"
    "DEFAULT_QUERIES": {
        "qview_cde_user": {
            n_("00_query_cde_user_all"): Query(
                "qview_cde_user", QUERY_SPECS['qview_cde_user'],
                ("personas.id", "given_names", "family_name"),
                (("is_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("10_query_cde_user_trial_members"): Query(
                "qview_cde_user", QUERY_SPECS['qview_cde_user'],
                ("personas.id", "given_names", "family_name"),
                (("trial_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("20_query_cde_user_expuls"): Query(
                "qview_cde_user", QUERY_SPECS['qview_cde_user'],
                ("personas.id", "given_names", "family_name", "address",
                 "address_supplement", "postal_code", "location", "country"),
                (("is_member", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        "qview_archived_persona": {
            n_("00_query_archived_persona_all"): Query(
                "qview_archived_persona",
                QUERY_SPECS['qview_archived_persona'],
                ("personas.id", "given_names", "family_name", "notes"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        "qview_event_user": {
            n_("00_query_event_user_all"): Query(
                "qview_event_user", QUERY_SPECS['qview_event_user'],
                ("personas.id", "given_names", "family_name", "birth_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("10_query_event_user_minors"): Query(
                "qview_event_user", QUERY_SPECS['qview_event_user'],
                ("persona.persona_id", "given_names", "family_name",
                 "birthday"),
                (("birthday", QueryOperators.greater,
                  deduct_years(now().date(), 18)),),
                (("birthday", True), ("family_name", True),
                 ("given_names", True))),
        },
        "qview_core_user": {
            n_("00_query_core_user_all"): Query(
                "qview_persona", QUERY_SPECS['qview_core_user'],
                ("personas.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("10_query_core_any_admin"): Query(
                "qview_persona", QUERY_SPECS['qview_core_user'],
                ("personas.id", "given_names", "family_name", "is_ml_admin",
                 "is_event_admin", "is_assembly_admin", "is_cde_admin",
                 "is_core_admin", "is_meta_admin"),
                (("is_ml_admin,is_event_admin,is_assembly_admin,"
                  "is_cde_admin,is_core_admin,is_meta_admin",
                  QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        "qview_assembly_user": {
            n_("00_query_assembly_user_all"): Query(
                "qview_persona", QUERY_SPECS['qview_persona'],
                ("persona.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("02_query_assembly_user_admin"): Query(
                "qview_persona", QUERY_SPECS['qview_persona'],
                ("persona.id", "given_names", "family_name",
                 "is_assembly_admin"),
                (("is_assembly_admin", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
        "qview_ml_user": {
            n_("00_query_ml_user_all"): Query(
                "qview_persona", QUERY_SPECS['qview_persona'],
                ("persona.id", "given_names", "family_name"),
                tuple(),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
            n_("02_query_ml_user_admin"): Query(
                "qview_persona", QUERY_SPECS['qview_persona'],
                ("persona.id", "given_names", "family_name",
                 "is_ml_admin"),
                (("is_ml_admin", QueryOperators.equal, True),),
                (("family_name", True), ("given_names", True),
                 ("personas.id", True))),
        },
    },

    "DEFAULT_QUERIES_REGISTRATION":
        generate_event_registration_default_queries,

}

#: defaults for :py:class:`SecretsConfig`
_SECRECTS_DEFAULTS = {
    # database users
    "CDB_DATABASE_ROLES": {
        "cdb_anonymous": "012345678901234567890123456789",
        "cdb_persona": "abcdefghijklmnopqrstuvwxyzabcd",
        "cdb_member": "zyxwvutsrqponmlkjihgfedcbazyxw",
        "cdb_admin": "9876543210abcdefghijklmnopqrst"
    },

    # salting value used for verifying sensitve url parameters
    "URL_PARAMETER_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",

    # salting value used for verifying password reset authorization
    "RESET_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",

    # key to use by mailing list software for authentification
    "ML_SCRIPT_KEY": "c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3",

    # mailman REST API password
    "MAILMAN_PASSWORD": "secret",

    # password for mailman to retrieve templates
    "MAILMAN_BASIC_AUTH_PASSWORD": "secret",

    # provisional API token for resolve API
    "RESOLVE_API_TOKEN": "secret",
}


class BasicConfig(collections.abc.Mapping):
    """Global configuration for elementary options.

    This is the global configuration which is the same for all
    processes. This is to be used when no invocation context is
    available (or it is infeasible to get at). There is no way to
    override the values on invocation, so the amount of values handled
    by this should be as small as possible.
    """

    def __init__(self):
        try:
            import cdedb.localconfig as config
            config = {
                key: getattr(config, key)
                for key in _BASIC_DEFAULTS.keys() & dir(config)
            }
        except ImportError:
            config = {}

        self._configlookup = collections.ChainMap(
            config,
            _BASIC_DEFAULTS
        )

    def __getitem__(self, key):
        return self._configlookup.__getitem__(key)

    def __iter__(self):
        return self._configlookup.__iter__()

    def __len__(self):
        return self._configlookup.__len__()


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
            spec = importlib.util.spec_from_file_location(
                "primaryconf", configpath
            )
            primaryconf = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(primaryconf)
            primaryconf = {
                key: getattr(primaryconf, key)
                for key in _DEFAULTS.keys() & dir(primaryconf)
            }
        else:
            primaryconf = {}

        try:
            import cdedb.localconfig as secondaryconf
            secondaryconf = {
                key: getattr(secondaryconf, key)
                for key in _DEFAULTS.keys() & dir(secondaryconf)
            }
        except ImportError:
            secondaryconf = {}

        self._configlookup = collections.ChainMap(
            primaryconf, secondaryconf, _DEFAULTS, _BASIC_DEFAULTS
        )

        for key in _BASIC_DEFAULTS.keys() & dir(primaryconf):
            _LOGGER.info(f"Ignored basic config entry {key} in {configpath}.")


class SecretsConfig(collections.abc.Mapping):
    """Container for secrets (i.e. passwords).

    This works like :py:class:`Config`, but is used for secrets. Thus
    the invocation specific overrides are imperative since passwords
    should not be left in a globally accessible spot.
    """

    def __init__(self, configpath):
        _LOGGER.debug(f"Initialising SecretsConfig with path {configpath}")
        if configpath:
            spec = importlib.util.spec_from_file_location(
                "primaryconf", configpath
            )
            primaryconf = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(primaryconf)
            primaryconf = {
                key: getattr(primaryconf, key)
                for key in _SECRECTS_DEFAULTS.keys() & dir(primaryconf)
            }
        else:
            primaryconf = {}

        try:
            import cdedb.localconfig as secondaryconf
            secondaryconf = {
                key: getattr(secondaryconf, key)
                for key in _SECRECTS_DEFAULTS.keys() & dir(secondaryconf)
            }
        except ImportError:
            secondaryconf = {}

        self._configlookup = collections.ChainMap(
            primaryconf, secondaryconf, _SECRECTS_DEFAULTS
        )

    def __getitem__(self, key):
        return self._configlookup.__getitem__(key)

    def __iter__(self):
        return self._configlookup.__iter__()

    def __len__(self):
        return self._configlookup.__len__()