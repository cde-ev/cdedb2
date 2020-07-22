#!/usr/bin/env python3

"""Generic scripting functionality.

This should be used in scripts to make them more uniform and cut down
on boilerplate.

Additionally this provides some level of guidance on how to interact
with the production environment.
"""

import getpass
import gettext

import psycopg2
import psycopg2.extras
import psycopg2.extensions

from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.event import EventBackend
from cdedb.common import make_proxy
from cdedb.database.connection import IrradiatedConnection, Atomizer

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)


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
        self.notifications = None
        self.urls = None
        self.requestargs = None
        self.urlmap = None
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
        self._errors = None
        self.validation_appraised = True
        self.csrf_alert = False


def setup(persona_id, dbuser, dbpassword, check_system_user=True, dbname='cdb'):
    """This sets up the database.

    :type persona_id: int
    :param persona_id: default ID for the owner of the generated request state
    :type dbuser: str
    :param dbuser: data base user for connection
    :type dbpassword: str
    :param dbpassword: password for database user
    :type check_system_user: bool
    :param check_system_user: toggle check for correct invoking user,
      you need to provide a really good reason to turn this off
    :rtype: callable
    :returns: a factory, that optionally takes a persona ID and gives
      you a facsimile request state object that can be used to call
      into the backends
    """
    if check_system_user and getpass.getuser() != "www-data":
        raise RuntimeError("Must be run as user www-data.")
    cstring = "dbname={} user={} password={} port=5432 host=localhost".format(
        dbname, dbuser, dbpassword)
    cdb = psycopg2.connect(cstring,
                           connection_factory=IrradiatedConnection,
                           cursor_factory=psycopg2.extras.RealDictCursor)
    cdb.set_client_encoding("UTF8")

    def rs(pid=persona_id):
        return RequestState(pid, cdb)

    return rs


def make_backend(realm, proxy=True):
    """Instantiate backend objects and wrap them in proxy shims.

    :type realm: str
    :param realm: selects backend to return
    :returns: a new backend
    """
    if realm == "core":
        backend = CoreBackend()
    elif realm == "cde":
        backend = CdEBackend()
    elif realm == "past_event":
        backend = PastEventBackend()
    elif realm == "ml":
        backend = MlBackend()
    elif realm == "assembly":
        backend = AssemblyBackend()
    elif realm == "event":
        backend = EventBackend()
    else:
        raise ValueError("Unrecognized realm")
    if proxy:
        return make_proxy(backend)
    else:
        return backend
