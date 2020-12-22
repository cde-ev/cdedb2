#!/usr/bin/env python3

import csv
import datetime
import gettext
import shutil
import time
from pathlib import Path
from pprint import pprint

import psycopg2
import psycopg2.extensions
import psycopg2.extras
import pytz

from cdedb.backend.assembly import AssemblyBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.core import CoreBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.database.connection import Atomizer, IrradiatedConnection

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
# cde = CdEBackend("/etc/cdedb-application-config.py")
past_event = PastEventBackend("/etc/cdedb-application-config.py")
# ml = MlBackend("/etc/cdedb-application-config.py")
# assembly = AssemblyBackend("/etc/cdedb-application-config.py")


# Start of actual script.

import collections

# Some additional imports.
import re

from cdedb.common import diacritic_patterns as dp

DEFAULT_ID = 1
DRY_RUN = False

# Mapping event shorthands to their pevent_ids.
pevent_map = {
    'ma2009-1': 233,
    'ma2010-1': 266,
    'ma2012-1': 334,
    'ma2013-1': 372,
    'ma2014-1': 411,
    'ma2015-1': 444,
    'ma2016-1': 484,
    'ma2017-1': 518,
    'pa2008-1': 199,
    'pa2009-1': 231,
    'pa2011-1': 295,
    'pa2012-1': 332,
    'pa2013-1': 369,
    'pa2014-1': 408,
    'pa2015-1': 445,
    'pa2016-1': 480,
    'pa2017-1': 515,
    'pa2018-1': 550,
    'sa2008-1': 200,
    'sa2009-1': 232,
    'sa2010-1': 265,
    'sa2011-1': 296,
    'sa2012-1': 333,
    'sa2013-1': 371,
    'sa2014-1': 410,
    'sa2015-1': 446,
    'sa2016-1': 482,
    'sa2017-1': 517,
    'sa2018-1': 552,
    'wa2009-1': 229,
    'wa2009-2': 230,
    'wa2010-1': 263,
    'wa2011-1': 294,
    'wa2012-1': 330,
    'wa2012-2': 331,
    'wa2013-1': 367,
    'wa2013-2': 268,
    'wa2014-1': 405,
    'wa2014-2': 406,
    'wa2015-1': 442,
    'wa2015-2': 443,
    'wa2016-1': 478,
    'wa2016-2': 479,
    'wa2017-1': 513,
    'wa2017-2': 514,
    'wa2018-1': 547,
    'wa2018-2': 548,
}


# Some helper functions.
def ddict():
    return collections.defaultdict(list)


def full_name(persona):
    return " ".join(x for x in (persona["given_names"],
                                persona["display_name"],
                                persona["family_name"],
                                persona.get("birth_name", ""))
                    if x)


def name_compare(target, name_parts):
    return all(re.search(dp(name), target, re.I) for name in name_parts)


course_pattern = re.compile(r"kurs(\w\w)-([12])")


# Read the data.
data = collections.defaultdict(ddict)

with open("/cdedb2/bin/kursleiter.txt", "r", encoding="utf-8") as infile:
    for line in infile:
        pevent, pcourse, *names = line.strip().split(" ")
        pcourse_nr, part = course_pattern.fullmatch(pcourse).groups()
        pevent_id = pevent_map[pevent[:-1] + part]
        data[pevent_id][pcourse_nr].append(names)

# pprint(data)

# Go through the data.
count = collections.defaultdict(int)
rs = rs(DEFAULT_ID)

for pevent_id in data:
    # For every event create a mapping of pcourse_nr to pcourse_id.
    pcourse_ids = past_event.list_past_courses(rs, pevent_id)
    pcourses = past_event.get_past_courses(rs, pcourse_ids)
    pcourse_map = {"{:0>2}".format(e["nr"]): e["id"] for e in pcourses.values()}

    for pcourse_nr in data[pevent_id]:
        try:
            pcourse_id = pcourse_map[pcourse_nr]
        except KeyError:
            count["fail"] += 1
            continue

        # For every course create a mapping of participant names to persona_id.
        pparticipants = past_event.list_participants(rs, pcourse_id=pcourse_id)
        persona_ids = {e["persona_id"]: e["is_instructor"]
                       for e in pparticipants.values()}
        personas = {}
        for anid in persona_ids:
            try:
                personas.update(core.get_cde_users(rs, (anid,)))
            except RuntimeError:
                personas.update(core.get_personas(rs, (anid,)))
        persona_map = {full_name(p): p["id"] for p in personas.values()}

        # For every data entry, try to find a persona that matches the name.
        for names in data[pevent_id][pcourse_nr]:
            persona_id = None
            for fn in persona_map:
                if name_compare(fn, names):
                    if persona_id is None:
                        persona_id = persona_map[fn]
                    else:
                        persona_id = -1

            if persona_id is None:
                count["fail"] += 1
                s = ("{} not found in https://db.cde-ev.de/db/cde/past/"
                     "event/{}/course/{}/show.")
                print(s.format(" ".join(names), pevent_id, pcourse_id))
            elif persona_id == -1:
                count["duplicate"] += 1
                s = "Found duplicate name: {} in Course {} of Event {}."
                print(s.format(" ".join(names), pcourse_id, pevent_id))
            else:
                s = "Found {} as instructor for Course {} of Event {}."
                print(s.format(" ".join(names), pcourse_id, pevent_id),
                      end=" ")
                # Remove the participant and add them as instructor,
                # if they were not already an instructor.
                if not persona_ids[persona_id]:
                    if not DRY_RUN:
                        past_event.remove_participant(
                            rs, pevent_id, pcourse_id, persona_id)
                        past_event.add_participant(
                            rs, pevent_id, pcourse_id, persona_id,
                            is_instructor=True, is_orga=False)
                    print("Added as instructor.")
                    count["success"] += 1
                else:
                    print("Already instructor.")
                    count["ignored"] += 1

print("----DRY RUN----" if DRY_RUN else "Changes applied:")
print("{} instructors successfully matched. {} not matched. {} ignored. "
      "{} duplicates.".format(count["success"],
                              count["fail"],
                              count["ignored"],
                              count["duplicate"]))
