#!/usr/bin/env python3

"""Fix emails to be lower case."""

import collections
import datetime
import gettext

import psycopg2
import psycopg2.extensions
import psycopg2.extras
import pytz

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.database.connection import IrradiatedConnection

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

#
# definitions
#

DEFAULT_ID = 5124

#
# helpers
#


def sanitize_db_input(obj):
    if isinstance(obj, str):
        if not obj:
            return None
    if (isinstance(obj, collections.abc.Iterable)
            and not isinstance(obj, (str, collections.abc.Mapping))):
        return [sanitize_db_input(x) for x in obj]
    else:
        return obj


def query_exec(sql, query, params):
    sanitized_params = tuple(sanitize_db_input(p) for p in params)
    with sql as conn:
        with conn.cursor() as cur:
            cur.execute(query, sanitized_params)
            return cur.rowcount


def query_one(sql, query, params):
    sanitized_params = tuple(sanitize_db_input(p) for p in params)
    with sql as conn:
        with conn.cursor() as cur:
            cur.execute(query, sanitized_params)
            return cur.fetchone()


def query_all(sql, query, params):
    sanitized_params = tuple(sanitize_db_input(p) for p in params)
    with sql as conn:
        with conn.cursor() as cur:
            cur.execute(query, sanitized_params)
            return tuple(x for x in cur.fetchall())


def insert(sql, table, data):
    keys = tuple(data.keys())
    query = "INSERT INTO {table} ({keys}) VALUES ({placeholders})"
    query = query.format(
        table=table, keys=", ".join(keys),
        placeholders=", ".join(("%s",) * len(keys)))
    params = tuple(data[key] for key in keys)
    query_exec(sql, query, params)


def fulltext(persona):
    attributes = (
        "id", "title", "username", "display_name", "given_names",
        "family_name", "birth_name", "name_supplement", "birthday",
        "telephone", "mobile", "address_supplement", "address",
        "postal_code", "location", "country", "address_supplement2",
        "address2", "postal_code2", "location2", "country2", "weblink",
        "specialisation", "affiliation", "timeline", "interests",
        "free_form")
    values = (str(persona[a]) for a in attributes if persona[a] is not None)
    return " ".join(values)


def now():
    return datetime.datetime.now(pytz.utc)


class User:
    def __init__(self, persona_id):
        self.persona_id = persona_id
        self.roles = {
            "anonymous", "persona", "cde", "event", "ml", "assembly",
            "cde_admin", "event_admin", "ml_admin", "assembly_admin",
            "core_admin", "meta_admin", "member", "searchable"}
        self.orga = set()
        self.moderator = set()
        self.username = None
        self.display_name = None
        self.given_names = None
        self.family_name = None


class RequestState:
    def __init__(self, persona_id, conn):
        self.ambience = None
        self.sessionkey = None
        self.user = User(persona_id)
        self.request = None
        self.response = None
        self.notifications = None
        self.urls = None
        self.requestargs = None
        self.urlmap = None
        self.errors = None
        self.values = None
        self.lang = "de"
        self.gettext = gettext.translation('cdedb', languages=("de",),
                                           localedir="/cdedb2/i18n").gettext
        self.ngettext = gettext.translation('cdedb', languages=("de",),
                                            localedir="/cdedb2/i18n").ngettext
        self._coders = None
        self.begin = None
        self.conn = conn
        self._conn = conn
        self.is_quiet = False


#
# create connections
#
conn_string = "dbname=cdb user=cdb password=987654321098765432109876543210 port=5432 host=localhost"
cdb = psycopg2.connect(conn_string,
                       connection_factory=IrradiatedConnection,
                       cursor_factory=psycopg2.extras.RealDictCursor)
cdb.set_client_encoding("UTF8")


def rs(persona_id):
    return RequestState(persona_id, cdb)


#
# prepare backends
#
core = CoreBackend("/etc/cdedb-application-config.py")
cde = CdEBackend("/etc/cdedb-application-config.py")
past_event = PastEventBackend("/etc/cdedb-application-config.py")
ml = MlBackend("/etc/cdedb-application-config.py")
assembly = AssemblyBackend("/etc/cdedb-application-config.py")

#
# Fix display names
#

query = "SELECT id, given_names, display_name FROM core.personas"
entries = query_all(cdb, query, tuple())
for entry in entries:
    if entry['id'] in (10997, 23515, 15876, 16792, 22534, 14996):
        # they have already changed their display_name
        continue
    if entry['given_names'] != entry['display_name']:
        update = {
            'id': entry['id'],
            'display_name': entry['given_names'],
        }
        core.change_persona(
            rs(DEFAULT_ID), update, generation=None, may_wait=False,
            change_note=("Repariere Rufnamen die bei der Migration"
                         " falsch initialisiert wurden."))
