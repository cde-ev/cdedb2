#!/usr/bin/env python3

import datetime
import gettext
import csv
from pprint import pprint

import psycopg2
import psycopg2.extras
import psycopg2.extensions

import pytz
import sys
from pathlib import Path
import shutil
import time

sys.path.insert(0, "/cdedb2/")

from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.event import EventBackend
from cdedb.database.connection import IrradiatedConnection, Atomizer

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

#
# helpers
#

class User:
    def __init__(self, persona_id):
        self.persona_id = persona_id
        self.roles = {
            "anonymous", "persona", "cde", "event", "ml", "assembly",
            "cde_admin", "event_admin", "ml_admin", "assembly_admin",
            "core_admin", "admin", "member", "searchable"}
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
# core = CoreBackend("/etc/cdedb-application-config.py")
# cde = CdEBackend("/etc/cdedb-application-config.py")
# past_event = PastEventBackend("/etc/cdedb-application-config.py")
# ml = MlBackend("/etc/cdedb-application-config.py")
# assembly = AssemblyBackend("/etc/cdedb-application-config.py")
event = EventBackend("/etc/cdedb-application-config.py")

# Start of actual script.

DEFAULT_ID = 1

event_id = 1
part_id = 1

new_track = {
    'title': "Neue Kursschiene",
    'shortname': "Neu",
    'num_choices': 3,
    'sortkey': 1,
}
update_event = {
    'id': event_id,
    'parts': {
        part_id: {
            'tracks': {
                -1: new_track,
            }
        }
    }
}
event.set_event(rs(DEFAULT_ID), update_event)
