#!/usr/bin/env python3

"""This provides config objects for the CdEDB, that is: default values and
a way to override them. Any hardcoded values should be found in
here. An exception are the default queries, which are defined in `query_defaults.py`.

Each config object takes into account the default values found in here. They can
be overwritten with values in an additional config file, where the path to this
file has to be present as environment variable CDEDB_CONFIGPATH.
Note that setting those variable is mandatory, to prevent accidental misses.
"""

import collections
import collections.abc
import datetime
import decimal
import importlib.util
import logging
import os
import pathlib
import subprocess
from typing import Any, Iterator, Mapping, Union

import pytz

PathLike = Union[pathlib.Path, str]


# The default path were a configuration file is expected. It is easier to hardcode this
# at some places where the configpath environment variable is unfeasible (like in
# wsgi.py, the entry point of apache2). This reflects also the configpath were the
# autobuild, docker-compose and production expect the config per default.
DEFAULT_CONFIGPATH = pathlib.Path("/etc/cdedb/config.py")


def set_configpath(path: PathLike) -> None:
    """Helper to set the configpath as environment variable."""
    os.environ["CDEDB_CONFIGPATH"] = str(path)


def get_configpath() -> pathlib.Path:
    """Helper to get the config path from the environment."""
    path = os.environ.get("CDEDB_CONFIGPATH")
    if path:
        return pathlib.Path(path)
    else:
        raise RuntimeError("No config path set!")


_LOGGER = logging.getLogger(__name__)

_currentpath = pathlib.Path(__file__).resolve().parent.parent
if _currentpath.parts[0] != '/' or _currentpath.parts[-1] != 'cdedb':  # pragma: no cover
    raise RuntimeError("Failed to locate repository")
_repopath = _currentpath.parent

try:
    _git_commit = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=str(_repopath)).decode().strip()
except FileNotFoundError:  # pragma: no cover, only catch git executable not found
    with pathlib.Path(_repopath, '.git/HEAD').open() as head:
        _git_commit = head.read().strip()

    if _git_commit.startswith('ref'):
        with pathlib.Path(_repopath, '.git', _git_commit[len('ref: '):]).open() as ref:
            _git_commit = ref.read().strip()


#: defaults for :py:class:`Config`
_DEFAULTS = {
    ################
    # Global stuff #
    ################

    # file system path to this repository
    "REPOSITORY_PATH": _repopath,

    # name of database to use
    "CDB_DATABASE_NAME": "cdb",

    # host (name or ip) on which the database listens
    "DB_HOST": "localhost",

    # port on which the database listens, preferably a pooler like pgbouncer
    "DB_PORT": 6432,

    # host name where the ldap server is running
    "LDAP_HOST": "localhost",

    # port on which the ldap server listens
    # TODO switch to TLS port?
    "LDAP_PORT": 389,

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

    # Directory in which all logs will be saved. The name of the specific log file will
    # be determined by the instance generating the log. The global log is in 'cdedb.log'
    "LOG_DIR": pathlib.Path("/tmp/"),

    # Logging level for CdEDBs own log files
    "LOG_LEVEL": logging.INFO,

    # Logging level for syslog
    "SYSLOG_LEVEL": logging.WARNING,

    # Logging level for stdout
    "CONSOLE_LOG_LEVEL": None,

    # hash id of the current HEAD/running version
    "GIT_COMMIT": _git_commit,

    # default timezone for input and output
    "DEFAULT_TIMEZONE": pytz.timezone('CET'),

    ##################
    # Frontend stuff #
    ##################

    # timeout for protected url parameters to prevent replay
    "PARAMETER_TIMEOUT": datetime.timedelta(hours=1),
    # timeout for protected parameters, that are not security related
    "UNCRITICAL_PARAMETER_TIMEOUT": datetime.timedelta(days=1),
    # timeoue for parameters, in unsuspected emails (triggered by another user)
    "EMAIL_PARAMETER_TIMEOUT": datetime.timedelta(days=2),
    # maximum length of rationale for requesting an account
    "MAX_RATIONALE": 500,
    # for shortnames longer than this, a ValidationWarning will be raised
    "SHORTNAME_LENGTH": 10,
    # a bit longer, but still a shortname
    "LEGACY_SHORTNAME_LENGTH": 30,
    # minimal number of input characters to start a search for personas
    # fitting an intelligent input field
    "NUM_PREVIEW_CHARS": 3,
    # maximum length of personas presented via select persona API for selection
    # in an intelligent input field for core admins
    "NUM_PREVIEW_PERSONAS_CORE_ADMIN": 12,
    # maximum length of personas presented via select persona API for any other
    # user
    "NUM_PREVIEW_PERSONAS": 3,
    #: Default amount of lines shown in logs shown in the frontend
    "DEFAULT_LOG_LENGTH": 50,
    #: Default country code to be used
    "DEFAULT_COUNTRY": "DE",
    # Available languages
    "I18N_LANGUAGES": ("de", "en", "la"),
    # Advertised languages in the UI
    "I18N_ADVERTISED_LANGUAGES": ("de", "en"),

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
    # default subject prefix
    "DEFAULT_PREFIX": "[CdE]",
    # domain for emails (determines message id)
    "MAIL_DOMAIN": "db.cde-ev.de",
    # host to use for sending emails
    "MAIL_HOST": "localhost",
    # email for internal system trouble notifications
    "TROUBLESHOOTING_ADDRESS": "admin@cde-ev.de",

    # email for cde account requests
    "CDE_ADMIN_ADDRESS": "cde-admins@cde-ev.de",
    # email for event account requests
    "EVENT_ADMIN_ADDRESS": "event-admins@cde-ev.de",
    # email for ml account requests
    "ML_ADMIN_ADDRESS": "ml-admins@cde-ev.de",
    # email for replies to assembly mails
    "ASSEMBLY_ADMIN_ADDRESS": "vorstand@cde-ev.de",

    # email for privilege changes
    "META_ADMIN_ADDRESS": "admin@cde-ev.de",

    # email for ballot tallies
    "BALLOT_TALLY_ADDRESS": "wahlbekanntmachung@lists.cde-ev.de",
    # mailinglist for ballot tallies
    "BALLOT_TALLY_MAILINGLIST_URL": "https://db.cde-ev.de/db/ml/mailinglist/91/show",

    # mailman REST API host
    "MAILMAN_HOST": "localhost:8001",
    # mailman REST API user
    "MAILMAN_USER": "restadmin",
    # user for mailman to retrieve templates
    "MAILMAN_BASIC_AUTH_USER": "mailman",

    #################
    # Backend stuff #
    #################

    #
    # Core stuff
    #

    # amount of time after which an inactive account may be archived.
    "AUTOMATED_ARCHIVAL_CUTOFF": datetime.timedelta(days=365*2),

    #
    # Session stuff
    #

    # session parameters
    "SESSION_TIMEOUT": datetime.timedelta(days=2),
    "SESSION_LIFESPAN": datetime.timedelta(days=7),

    # Maximum concurrent sessions per user.
    "MAX_ACTIVE_SESSIONS": 5,

    #
    # CdE stuff
    #

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

    # Bank accounts. First is shown to participants,
    # second is a web label for orgas
    "EVENT_BANK_ACCOUNTS": (
        ("DE26370205000008068900", "DE26370205000008068900"),
    ),
    # Rate limit for orgas adding persons to their event
    # number of persons per day
    "ORGA_ADD_LIMIT": 10,

    ###############
    # Query stuff #
    ###############

    # this can be found and overridden in cdedb2/query_defaults.py

}

#: defaults for :py:class:`SecretsConfig`
_SECRECTS_DEFAULTS = {
    # database users
    "CDB_DATABASE_ROLES": {
        "nobody": "nobody",  # use only to set up internal details like sample-data!
        "cdb_anonymous": "012345678901234567890123456789",
        "cdb_persona": "abcdefghijklmnopqrstuvwxyzabcd",
        "cdb_member": "zyxwvutsrqponmlkjihgfedcbazyxw",
        "cdb_admin": "9876543210abcdefghijklmnopqrst",
        "cdb": "987654321098765432109876543210",  # only used for testsuite
    },

    # salting value used for verifying sensitve url parameters
    "URL_PARAMETER_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",

    # salting value used for verifying password reset authorization
    "RESET_SALT": "aoeuidhtns9KT6AOR2kNjq2zO",


    # mailman REST API password
    "MAILMAN_PASSWORD": "secret",

    # password for mailman to retrieve templates
    "MAILMAN_BASIC_AUTH_PASSWORD": "secret",

    # fixed tokens for API access
    "API_TOKENS": {
        # resolve API for CyberAka
        "resolve": "a1o2e3u4i5d6h7t8n9s0",

        # zero-config partial export in offline mode
        "quick_partial_export": "y1f2i3d4x5b6",
    },

    # ldap related stuff
    "LDAP_DUA_PW": {
        "admin": "secret",
        "apache": "secret",
        "cloud": "secret",
        "cyberaka": "secret",
        "dokuwiki": "secret",
    },
}


class Config(Mapping[str, Any]):
    """Main configuration.

    Can be overridden through the file specified by the CDEDB_CONFIGPATH environment
    variable. However, this does not allow to introduce keys which are not present in
    the _DEFAULT configuration.
    """

    def __init__(self) -> None:
        configpath = get_configpath()
        self._configpath = configpath

        name = self.__class__.__name__
        _LOGGER.debug(f"Initialising {name} with path {configpath}")

        if not configpath:
            raise RuntimeError(f"No configpath for {name} provided!")
        if not pathlib.Path(configpath).is_file():
            raise RuntimeError(f"During initialization of {name}, config file"
                               f" {configpath} not found!")

        override = self._process_config_overwrite()
        self._configchain = collections.ChainMap(override, _DEFAULTS)

    def _process_config_overwrite(self) -> Any:
        """Allow only keys which are already present in _DEFAULT."""
        spec = importlib.util.spec_from_file_location("override", str(self._configpath))
        if not spec:
            raise ImportError
        override = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(override)  # type: ignore
        override = {
            key: getattr(override, key)
            for key in _DEFAULTS.keys() & set(dir(override))
        }
        return override

    def __getitem__(self, key: str) -> Any:
        return self._configchain.__getitem__(key)

    def __iter__(self) -> Iterator[str]:
        return self._configchain.__iter__()

    def __len__(self) -> int:
        return self._configchain.__len__()


class TestConfig(Config):
    """Main configuration for tests.

    This is very similar to Config. The big difference is that it allows adding
    arbitrary new keys through the config override. This is useful to bundle
    all the configuration in our testsuite in a configfile.
    """

    def _process_config_overwrite(self) -> Any:
        """Allow additional keys which are not present in _DEFAULT."""
        spec = importlib.util.spec_from_file_location("override", str(self._configpath))
        if not spec:
            raise ImportError
        override = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(override)  # type: ignore
        override = {key: getattr(override, key) for key in dir(override)}
        return override


class SecretsConfig(Mapping[str, Any]):
    """Container for secrets (i.e. passwords).

    This works like :py:class:`Config`, but is used for secrets. Thus
    the invocation specific overrides are imperative since passwords
    should not be left in a globally accessible spot.
    """

    def __init__(self) -> None:
        # TODO switch to own config file
        configpath = get_configpath()
        _LOGGER.debug(f"Initialising SecretsConfig with path {configpath}")

        if not configpath:
            raise RuntimeError("No configpath for SecretsConfig provided!")
        if not pathlib.Path(configpath).is_file():
            raise RuntimeError(f"During initialization of TestConfig, config file"
                               f" {configpath} not found!")

        spec = importlib.util.spec_from_file_location("override", str(configpath))
        if not spec:
            raise ImportError
        override = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(override)  # type: ignore
        override = {
            key: getattr(override, key)
            for key in _SECRECTS_DEFAULTS.keys() & set(dir(override))
        }

        self._configchain = collections.ChainMap(override, _SECRECTS_DEFAULTS)

    def __getitem__(self, key: str) -> Any:
        return self._configchain.__getitem__(key)

    def __iter__(self) -> Iterator[str]:
        return self._configchain.__iter__()

    def __len__(self) -> int:
        return self._configchain.__len__()
