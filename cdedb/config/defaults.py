import datetime as _datetime
import decimal as _decimal
import logging as _logging
import pathlib as _pathlib
import subprocess as _subprocess
import zoneinfo as _zoneinfo

_currentdir = _pathlib.Path(__file__).resolve().parent.parent
if _currentdir.parts[0] != '/' or _currentdir.parts[-1] != 'cdedb':  # pragma: no cover
    raise RuntimeError("Failed to locate repository")
_repopath = _currentdir.parent


try:
    _git_commit = (
        _subprocess
        .check_output(("git", "rev-parse", "HEAD"), cwd=_repopath)
        .decode()
        .strip()
    )

except FileNotFoundError:  # pragma: no cover, only catch git executable not found
    _git_commit = (_repopath / ".git/HEAD").read_text().strip()

    if _git_commit.startswith("ref: "):
        _git_commit = (
            (_repopath / ".git" / _git_commit.removeprefix("ref: ")).read_text().strip()
        )
except _subprocess.CalledProcessError as e:  # pragma: no cover
    # It can happen that we use a git worktree where the primary repository
    # is outside of the sandbox/VM in which we are running. Testing this is infeasible.
    _git_reference = (_repopath / ".git").read_text().strip()
    if not _git_reference.startswith("gitdir: "):
        raise RuntimeError("Unable to determine git commit") from e

    # The commit is primarily used for cache busting
    # so there is not harm to set it to the empty string during development.
    _git_commit = ""


################
# Global stuff #
################

# host of the http application, since we do not trust apaches Host Header
HTTP_HOSTS = [
    "localhost",  # used in test suite
    "localhost:20443",  # regular forwarded port from vm
    "localhost:8443",  # used by docker
    "localhost:5000",  # interactive debugger
]

# file system path to this repository
REPOSITORY_PATH = _repopath

# path to the file which holds the password overrides of the SecretsConfig
SECRETS_CONFIGPATH = _pathlib.Path("/etc/cdedb/public-secrets.py")

# name of database to use
CDB_DATABASE_NAME = "cdb"

# host (name or ip) on which the database listens
DB_HOST = "localhost"

# port on which the database listens, preferably a pooler like pgbouncer
DB_PORT = 6432

# port of the db itself, for skipping pooler during tests or deploys.
DIRECT_DB_PORT = 5432

# host name where the ldap server is running
LDAP_HOST = "sandbox.cdedb.virtual"
# port on which the ldap server listens
LDAP_PORT = 636
# path to ldaps .pem and .key files
LDAP_PEM_PATH = _repopath / "related" / "auto-build" / "files" / "stage2" / "ldap.pem"
LDAP_KEY_PATH = _repopath / "related" / "auto-build" / "files" / "stage2" / "ldap.key"

# True for offline versions running on academies
CDEDB_OFFLINE_DEPLOYMENT = False

# If True only core admins are granted access
LOCKDOWN = False

# True for development instances
CDEDB_DEV = False

# True when running within unit test environment
CDEDB_TEST = False

# place for uploaded data
STORAGE_DIR = _pathlib.Path("/var/lib/cdedb/")

# log level of our application
DEFAULT_LOG_LEVEL = _logging.INFO
LOG_LEVEL = DEFAULT_LOG_LEVEL

# hash id of the current HEAD/running version
GIT_COMMIT = _git_commit

# default timezone for input and output
DEFAULT_TIMEZONE = _zoneinfo.ZoneInfo("Europe/Berlin")

# droids which are allowed access during lockdown.
INFRASTRUCTURE_DROIDS = {"resolve"}

##################
# Frontend stuff #
##################

# timeout for protected url parameters to prevent replay
PARAMETER_TIMEOUT = _datetime.timedelta(hours=3)
# timeout for protected parameters, that are not security related or are triggered by another user.
EXTENDED_PARAMETER_TIMEOUT = _datetime.timedelta(days=5)
# maximum length of rationale for requesting an account
MAX_RATIONALE = 500
# for shortnames longer than this, a ValidationWarning will be raised
SHORTNAME_LENGTH = 10
# a bit longer, but still a shortname
LEGACY_SHORTNAME_LENGTH = 30
# minimal number of input characters to start a search for personas
# fitting an intelligent input field
NUM_PREVIEW_CHARS = 3
# maximum length of personas presented via select persona API for selection
# in an intelligent input field for privileged users (core admins and orgas)
NUM_PREVIEW_PERSONAS_PRIVILEGED = 12
# maximum length of personas presented via select persona API for any other
# user
NUM_PREVIEW_PERSONAS = 3
#: Default amount of lines shown in logs shown in the frontend
DEFAULT_LOG_LENGTH = 50
#: Default country code to be used
DEFAULT_COUNTRY = "DE"
# Available languages
I18N_LANGUAGES = ("de", "en", "la")
# Advertised languages in the UI
I18N_ADVERTISED_LANGUAGES = ("de", "en")
# timeout for cleaning up genesis cases
GENESIS_CLEANUP_TIMEOUT = _datetime.timedelta(days=90)

###############
# email stuff #
###############

# email for administrative notifications
MANAGEMENT_ADDRESS = "verwaltung@cde-ev.de"
# default return address for mails
DEFAULT_REPLY_TO = "verwaltung@cde-ev.de"
# default return path for bounced mail
DEFAULT_RETURN_PATH = "bounces@cde-ev.de"
# default sender address for mails
DEFAULT_SENDER = '"CdE-Datenbank" <datenbank@cde-ev.de>'
# noreply sender for sensitive mails
NOREPLY_SENDER = '"CdE-Datenbank" <no-reply@cde-ev.de>'
NOREPLY_ADDRESS = "no-reply@cde-ev.de"
# default subject prefix
DEFAULT_PREFIX = "[CdE]"
# domain for emails (determines message id)
MAIL_DOMAIN = "db.cde-ev.de"
# host to use for sending emails
MAIL_HOST = "localhost"
# email for internal system trouble notifications
TROUBLESHOOTING_ADDRESS = "admin@cde-ev.de"

# email for cde account requests
CDE_USER_MANAGEMENT_ADDRESS = "cde-admins@cde-ev.de"
# email for event account requests
EVENT_USER_MANAGEMENT_ADDRESS = "event-admins@cde-ev.de"
# email for ml account requests
ML_USER_MANAGEMENT_ADDRESS = "ml-admins@cde-ev.de"
# email for assembly user management
ASSEMBLY_USER_MANAGEMENT_ADDRESS = "vorstand@cde-ev.de"

# email for cde realm management
CDE_ADMIN_ADDRESS = "cde-admins@cde-ev.de"
# email for event management
EVENT_ADMIN_ADDRESS = "event-admins@cde-ev.de"
# email for mailinglist management
ML_ADMIN_ADDRESS = "ml-admins@cde-ev.de"
# email for replies to assembly mails
ASSEMBLY_ADMIN_ADDRESS = "vorstand@cde-ev.de"
# email for replies to finance mails
FINANCE_ADMIN_ADDRESS = "buchhaltung@lists.cde-ev.de"
# email for event related finance mails
EVENT_FINANCE_ADMIN_ADDRESS = "aka-finanzen@lists.cde-ev.de"
# email for complaint case related mails
COMPLAINT_ADMIN_ADDRESS = "fallkoordination@lists.cde-ev.de"

# email for privilege changes
META_ADMIN_ADDRESS = "admin@cde-ev.de"

# email for ballot tallies
BALLOT_TALLY_ADDRESS = "wahlbekanntmachung@lists.cde-ev.de"
# mailinglist for ballot tallies
BALLOT_TALLY_MAILINGLIST_URL = "https://db.cde-ev.de/db/ml/mailinglist/91/show"

# email addresses for the global contact form
CONTACT_ADDRESSES = {
    "vorstand@cde-ev.de": "Vorstand",
    "probleme-mit-dem-vorstand@lists.cde-ev.de": "Ansprechpartner für Probleme mit dem Vorstand",
    "fallkoordination@lists.cde-ev.de": "Vermittlungs- und Beschwerdestelle für personenbezogene Probleme",
    "feedback@lists.cde-ev.de": "Feedback-Team",
}

# mailman REST API host
MAILMAN_HOST = "localhost:8001"
# mailman REST API user
MAILMAN_USER = "restadmin"
# user for mailman to retrieve templates
MAILMAN_BASIC_AUTH_USER = "mailman"
# aliases which are recognized for mailinglists
MAILMAN_ACCEPTABLE_ALIASES = {
    "verwaltung@lists.cde-ev.de": ["datenbank@cde-ev.de"],
    "vorstand@lists.cde-ev.de": [
        "info@cde-ev.de",
        "thomas.riebe@foerderverein-eisenberg.de",
    ],
    "akademien@lists.cde-ev.de": ["thomas.riebe@foerderverein-eisenberg.de"],
    "doku@lists.cde-ev.de": ["team@dokuforge.de"],
    "dokuforge2@lists.cde-ev.de": ["df2@dokuforge.de"],
    "vanconference25-orga@aka.cde-ev.de": ["vanconference2@aka.cde-ev.de"],
    "sk-schulung24-orga@aka.cde-ev.de": ["schuko24-orga@aka.cde-ev.de"],
}

#################
# Backend stuff #
#################

#
# Core stuff
#

# amount of time after which an inactive account may be archived.
AUTOMATED_ARCHIVAL_CUTOFF = _datetime.timedelta(days=365 * 2)
# ID of the last event where we do not care about remaining_owed.
EVENT_ARCHIVAL_BALANCE_CUTOFF = 64  # NachhaltigkeitsAkademie 2023

#
# Session stuff
#

# time which a session remains active without sending a new request
SESSION_TIMEOUT = _datetime.timedelta(days=2)
# maximum time which a session may remain active
SESSION_LIFESPAN = _datetime.timedelta(days=7)
# minimum time which sessions stay in the database
SESSION_SAVETIME = _datetime.timedelta(days=30)

# Maximum concurrent sessions per user.
MAX_ACTIVE_SESSIONS = 5

#
# CdE stuff
#

# maximal number of data sets a normal user is allowed to view per day
QUOTA_VIEWS_PER_DAY = 42
# maximal number of results for a member search
MAX_MEMBER_SEARCH_RESULTS = 200
# available radius options for nearby search
NEARBY_SEARCH_RADII = {
    5_000: "5 km",
    10_000: "10 km",
    30_000: "30 km",
    80_000: "80 km",
}
# id of the first semester for which relevant data exists.
MIN_RELEVANT_SEMESTER = 42
# amount deducted from balance each period (semester)
MEMBERSHIP_FEE = _decimal.Decimal('4.00')
# probably always 1 or 2
PERIODS_PER_YEAR = 2
# the minimal and maximal donation we accept per annual lastschrifts
MINIMAL_LASTSCHRIFT_DONATION = _decimal.Decimal('2.00')
MAXIMAL_LASTSCHRIFT_DONATION = _decimal.Decimal('1000.00')
# the predefined donation amount of a lastschrift, if the user didn't specified one
TYPICAL_LASTSCHRIFT_DONATION = _decimal.Decimal('20.00')

# Address of the originating organization
# The actual address consists of multiple lines
SEPA_SENDER_ADDRESS = ("Musterstrasse 123", "00000 Teststadt")
SEPA_SENDER_COUNTRY = "DE"
# "Gläubiger-ID" for direct debit transfers
SEPA_GLAEUBIGERID = "DE00ZZZ00099999999"
# Old "Gläubiger-ID" if it changed.
SEPA_ORIGINAL_GLAEUBIGERID = ""
# Date at which SEPA was introduced
SEPA_INITIALISATION_DATE = _datetime.date(2013, 7, 30)
# Date after which SEPA was used exclusively
SEPA_CUTOFF_DATE = _datetime.date(2013, 10, 14)
# Timespan to wait between issuing of SEPA order and fulfillment
SEPA_PAYMENT_OFFSET = _datetime.timedelta(days=17)
# processing fee we incur if a transaction is rolled back
SEPA_ROLLBACK_FEE = _decimal.Decimal('4.50')

#
# event stuff
#

# Rate limit for orgas adding persons to their event
# number of persons per day
ORGA_ADD_LIMIT = 10

#
# complaint stuff
#

# time which a access to a case remains active for.
COMPLAINT_UNLOCK_TIMEOUT = _datetime.timedelta(minutes=30)
COMPLAINT_ENTRY_VERSION_PURGE_DELAY = _datetime.timedelta(days=10)

###############
# Query stuff #
###############

# this can be found and overridden in cdedb2/query_defaults.py
