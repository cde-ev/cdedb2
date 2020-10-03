#!/usr/bin/env python3

import datetime
import gettext
import csv
from pprint import pprint

import psycopg2
import psycopg2.extras
import psycopg2.extensions

import pytz
from pathlib import Path
import shutil
import time

from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database.connection import IrradiatedConnection, Atomizer

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

#
# definitions
#

DEFAULT_ID = 1


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
cde = CdEBackend("/etc/cdedb-application-config.py")
past_event = PastEventBackend("/etc/cdedb-application-config.py")
ml = MlBackend("/etc/cdedb-application-config.py")
assembly = AssemblyBackend("/etc/cdedb-application-config.py")

#
# create new assembly
#
new_assembly = {
    "title": "Sonstiges",
    "description": None,
    "signup_end": datetime.datetime(2222, 2, 2),
    "notes": None,
    "is_active": False
}

existing_assemblies = {v["title"]: k for k, v in
                       assembly.list_assemblies(rs(DEFAULT_ID)).items()}
new_id = existing_assemblies.get(new_assembly["title"])
if not new_id:
    new_id = assembly.create_assembly(rs(DEFAULT_ID), new_assembly)

#
# prepare files
#
year_to_assembly_map = {
    2008: 1,
    2009: 2,
    2010: 3,
    2011: 4,
    2012: 5,
    2013: 6,
    2014: 7,
    2015: 8,
    2016: 9,
    2017: 10,
    2018: 11,
}

files = {
    # General files
    7: {'assembly_id': new_id,
        'filename': 'cde-gruendung-2005-10-28.pdf',
        'title': 'CdE e.V.: Diskussionstreffen zur Vereinsgründung'},
    55: {'assembly_id': new_id,
         'filename': 'cde-kommentar.pdf',
         'title': 'CdE-Satzungskommentar, 1. Auflage (Stand: 1.10.2010)'},
    93: {'assembly_id': new_id,
         'filename': 'cde-kommentar-v2.pdf',
         'title': 'CdE-Satzungskommentar, 2. Auflage (Stand 2013)'},
    56: {'assembly_id': new_id,
         'filename': 'mgv-wasistdas-2008.pdf',
         'title': 'Mitgliederversammlung - was ist das (2008)?'},
    57: {'assembly_id': new_id,
         'filename': 'mgv-wasistdas-2011.pdf',
         'title': 'Mitgliederversammlung - was ist das (2011)?'},
    76: {'assembly_id': new_id,
         'filename': 'aktiventreffen_2008.pdf',
         'title': 'Aktiventreffen PfingstAkademie 2008'},
    8: {'assembly_id': new_id,
        'filename': 'aktiventreffen_2009.pdf',
        'title': 'Aktiventreffen AkadeMai 2009'},
    6: {'assembly_id': new_id,
        'filename': 'aktiventreffen_2010.pdf',
        'title': 'Aktiventreffen PfingstAkademie 2010'},
    25: {'assembly_id': new_id,
         'filename': 'aktiventreffen_2011.pdf',
         'title': 'Aktiventreffen PfingstAkademie 2011'},
    26: {'assembly_id': new_id,
         'filename': 'aktiventreffen_2012.pdf',
         'title': 'Aktiventreffen PfingstAkademie 2012'},
    95: {'assembly_id': new_id,
         'filename': 'aktiventreffen_2013.pdf',
         'title': 'Aktiventreffen PfingstAkademie 2013'},
    148: {'assembly_id': new_id,
          'filename': 'aktiventreffen_2014.pdf',
          'title': 'Aktiventreffen PfingstAkademie 2014'},
    191: {'assembly_id': new_id,
          'filename': 'aktiventreffen_2015.pdf',
          'title': 'Aktiventreffen MayFestspiele 2015'},
    193: {'assembly_id': new_id,
          'filename': 'aktiventreffen_2016.pdf',
          'title': 'Aktiventreffen PfingstAkademie 2016'},
    222: {'assembly_id': new_id,
          'filename': 'aktiventreffen_2017.pdf',
          'title': 'Aktiventreffen PfingstAkademie 2017'},

    # MGV 2008
    9: {'assembly_id': year_to_assembly_map[2008],
        'filename': 'kassenpruefung_2008_bartko.pdf',
        'title': 'Kassenprüfung 2008 Bartko'},
    14: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top03_Initiative25p.pdf',
         'title': 'TOP03 Initiative 25+'},
    17: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top01_Verhaeltnis-DSA-CdE.pdf',
         'title': 'TOP01 Änderung der Satzung (Verhältnis DSA und CdE) [Stand: 24.11.2008]'},
    22: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top02_Beteiligungsquorum.pdf',
         'title': 'TOP02 Änderung der Satzung (Beteiligungsquoren)'},
    38: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top05_Mitgliedsbeitrag.pdf',
         'title': 'TOP05 Änderung des Mitgliederbeschlusses über die Höhe des Mitgliedsbeitrags (Restguthaben) [Stand: 04.11.2008]'},
    45: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top04_Kennenlernzeit.pdf',
         'title': 'TOP04 Änderung des Mitgliederbeschlusses über die Kennenlernzeit [Stand: 04.11.2008]'},
    59: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top07_Aufnahme-CdE-Akademien.pdf',
         'title': 'TOP07 Änderung des Mitgliederbeschlusses zu §4 Abs. 2 (Aufnahme CdE-Akademien) [Stand: 06.11.2008]'},
    61: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top08_E-Piano.pdf',
         'title': 'TOP08 Anschaffung eines elektrischen Klaviers [Stand: 04.11.2008]'},
    66: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'mgv2008_top06_MatheAkademie.pdf',
         'title': 'TOP06 Änderung des Mitgliederbeschlusses zu §4 Abs. 2 (Aufnahme MatheAkademie)'},
    68: {'assembly_id': year_to_assembly_map[2008],
         'filename': 'kassenpruefung_2008_zimmermann.pdf',
         'title': 'Kassenprüfung 2008 Zimmermann'},

    # MGV 2009
    5: {'assembly_id': year_to_assembly_map[2009],
        'filename': 'mgv2009_top01_Kinderfreundlichkeit-Burgdorf.pdf',
        'title': 'TOP01 Teilnahme von Eltern mit Kindern an CdE-Veranstaltungen (Verbesserung der Kinderfreundlichkeit): Antrag Burgdorf u.a. [Stand: 15.11.2009]'},
    15: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top04_Haftpflichtversicherung-Kempny.pdf',
         'title': 'TOP04 Finanzierung der Haftpflichtversicherung und Erhöhung des Mitgliedsbeitrags: Antrag Kempny u.a.'},
    24: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top03_Umfrage.pdf',
         'title': 'TOP03 Umfrage aus dem Jahr 2004 (Initiative 25++)'},
    33: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top04_Haftplichtversicherung-Pohle.pdf',
         'title': 'TOP04 Finanzierung der Haftpflichtversicherung und Erhöhung des Mitgliedsbeitrags: Antrag Pohle u.a. [Stand: 12.11.2009]'},
    42: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'kassenpruefung_2009_bartko.pdf',
         'title': 'Kassenprüfung 2009 Bartko'},
    58: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top01_Kinderfreundlichkeit-Harland-Koebler-Kempny.pdf',
         'title': 'TOP01 Teilnahme von Eltern mit Kindern an CdE-Veranstaltungen (Verbesserung der Kinderfreundlichkeit): Antrag Harland/Koebler/Kempny [Stand: 15.11.2009]'},
    62: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'kassenpruefung_2009_zimmermann.pdf',
         'title': 'Kassenprüfung 2009 Zimmermann'},
    67: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top03_Initiative25pp.pdf',
         'title': 'TOP03 Initiative 25++'},
    73: {'assembly_id': year_to_assembly_map[2009],
         'filename': 'mgv2009_top02_Vertretungsmacht.pdf',
         'title': 'TOP02 Änderung des Mitgliederbeschlusses über die Vertretungsmacht des Vorstands'},
    147: {'assembly_id': year_to_assembly_map[2009],
          'filename': 'mgv2009_protokoll.pdf',
          'title': 'Protokoll 2009'},

    # MGV 2010
    1: {'assembly_id': year_to_assembly_map[2010],
        'filename': 'mgv2010_top05_Haertefallregelung-Brodowski.pdf',
        'title': 'TOP05 Erfahrungen mit der Anwendung der Härtefallregelung: Antrag Brodowski u.a. [Stand: 11.11.2010]'},
    4: {'assembly_id': year_to_assembly_map[2010],
        'filename': 'mgv2010_top03_Gleichstellung-Hilfsantrag.pdf',
        'title': 'TOP03 Gleichstellung von DSA-ähnlichen Akademien: Hilfsantrag Helmsauer/Gall/Kempny/Mattauch [Stand: 13.11.2010, 2. Fassung]'},
    10: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top02_Aktivenforum-Bastian.pdf',
         'title': 'TOP02 Rechte des Aktivenforums: Antrag Bastian u.a. [Stand: 13.11.2010]'},
    11: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top02_Aktivenforum-Gall.pdf',
         'title': 'TOP02 Rechte des Aktivenforums: Antrag Gall u.a. [Stand: 17.11.2010]'},
    18: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top06_Praezisierungen.pdf',
         'title': 'TOP06 Verschiedene Präzisierungen [Stand: 13.11.2010]'},
    20: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'kassenpruefung_2010_hornung.pdf',
         'title': 'Kassenprüfung 2010 Hornung'},
    21: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top09_Fahrtkostenerstattung.pdf',
         'title': 'TOP09 Fahrtkostenerstattung'},
    28: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top05_Haertefallregelung.pdf',
         'title': 'TOP05 Erfahrungen mit der Anwendung der Härtefallregelung'},
    29: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top08_Rechtsformwechsel-BuB.pdf',
         'title': 'TOP08 Rechtsformwechsel von Bildung und Begabung GmbH und weitere Klarstellung'},
    30: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_protokoll.zip',
         'title': 'Protokoll 2010'},
    35: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top05_Haertefallregelung-Gall-Mattauch.pdf',
         'title': 'TOP05 Erfahrungen mit der Anwendung der Härtefallregelung: Antrag Gall/Mattauch [Stand: 13.11.2010, 2. Fassung]'},
    37: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top03_Gleichstellung-Fall-Gall-Mattauch.pdf',
         'title': 'TOP03 Gleichstellung von DSA-ähnlichen Akademien: Antrag Fall/Gall/Mattauch [Stand: 15.11.2010]'},
    40: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top11_Zahlenbereinigung.pdf',
         'title': 'TOP11 Zahlenbereinigung [Stand: 11.11.2010]'},
    44: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'kassenpruefung_2010_bartko',
         'title': 'Kassenprüfung 2010 Bartko'},
    47: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top03_Gleichstellung-Helmsauer-Kempny.pdf',
         'title': 'TOP03 Gleichstellung von DSA-ähnlichen Akademien: Antrag Helmsauer/Kempny [Stand: 13.11.2010]'},
    48: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top02_Aktivenforum-Nebenantrag-Gall.pdf',
         'title': 'TOP02 Rechte des Aktivenforums: Nebenantrag Gall u.a. [Stand: 14.11.2010]'},
    52: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top07_Wahlordnung.pdf',
         'title': 'TOP07 Änderung der Wahlordnung'},
    60: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top05_Abstimmungsvorlage.pdf',
         'title': 'TOP05 Erfahrungen mit der Anwendung der Härtefallregelung: Abstimmungsvorlage'},
    63: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top01_Mitglieder-Aktivenforum.pdf',
         'title': 'TOP01 Mitglieder und Gruppierungen des Aktivenforums'},
    64: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top10_Berichtspflichten.pdf',
         'title': 'TOP10 Berichtspflichten [Stand: 17.11.2010]'},
    70: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top02_Abstimmungsvorlage.pdf',
         'title': 'TOP02 Rechte des Aktivenforums: Abstimmungsvorlage'},
    72: {'assembly_id': year_to_assembly_map[2010],
         'filename': 'mgv2010_top04_Gleichstellung-Ausland.pdf',
         'title': 'TOP04 Gleichstellung von ausländischen Akademien [Stand: 15.11.2010]'},

    # MGV 2011
    16: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top02_Abstimmungsrecht-3.pdf',
         'title': 'TOP02 Änderung der Satzung (Abstimmungsrechtsänderung -- 3. Antrag [Stand: 19.11.2011])'},
    19: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top16_Rechtschreibung-Satzung.pdf',
         'title': 'TOP16 Sonstiges: Änderung der Satzung '
                  '(Rechtschreibberichtigung § 8 Absatz II)'},
    23: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'kassenpruefung_2011_keller.pdf',
         'title': 'Kassenorüfung 2011 Keller'},
    31: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'kassenpruefung_2011_hornung.pdf',
         'title': 'Kassenprüfung 2011 Hornung'},
    32: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top09_zweckgebundene-Spenden-Haertefaelle.pdf',
         'title': 'TOP09 Änderung des Mitgliederbeschlusses über die vertretungsmacht des Vorstands (zweckgebundene Spenden für Härtefälle)'},
    34: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top10_Probehalbjahr-Kurleiter.pdf',
         'title': 'TOP10 Änderung des Mitgliederbeschlusses über die Kennenlernzeit (Probehalbjahr für Kursleiter der SchülerAkademien)'},
    39: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top01_Abkuerzungen.pdf',
         'title': 'TOP01 Bereinigung der Verwendung von Abkürzungen im Binnenrecht: Änderung der Satzung'},
    41: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_protokoll.zip',
         'title': 'Protokoll 2011'},
    43: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top06_Redaktion-MB-VM.pdf',
         'title': 'TOP06 Änderung des Mitgliederbeschlusses über die Vertretungsmacht des Vorstands (Redaktionelle Änderung [Stand: 11.11.2011])'},
    46: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top02_Abstimmungsrecht-1.pdf',
         'title': 'TOP02 Änderung der Satzung (Abstimmungsrechtsänderung -- 1. Antrag [Stand: 17.11.2011])'},
    50: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top08_zweite-SommerAkademie.pdf',
         'title': 'TOP08 Änderung des Mitgliederbeschlusses über die Vertretungsmacht des Vorstands (Finanzierung einer zweiten SommerAkademie) [Stand: 29.10.2011]'},
    51: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top04_Aktivenforum.pdf',
         'title': 'TOP04 Änderung der Satzung (Eintritt ins Aktivenforum)'},
    54: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top11_Veranstaltungsmailingliste.pdf',
         'title': 'TOP11 Änderung des Mitgliederbeschlusses über die Kommunikation (Veranstaltungsmailingliste [Stand: 21.11.2011])'},
    69: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top07_Initiative25p.pdf',
         'title': 'TOP07 Änderung des Mitgliederbeschlusses über die Vertretungsmacht des Vorstands (Geld aus der Initiative 25+)'},
    71: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top05_Wahlordnung.pdf',
         'title': 'TOP05 Änderung der Wahlordnung'},
    74: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top02_Abstimmungsrecht-2.pdf',
         'title': 'TOP02 Änderung der Satzung (Abstimmungsrechtsänderung -- 2. Antrag [Stand: 10.11.2011])'},
    75: {'assembly_id': year_to_assembly_map[2011],
         'filename': 'mgv2011_top03_Aufnahme-Externe.pdf',
         'title': 'TOP03 Änderung der Satzung (§ 4 Abs. 3 S. 2 - Aufnahme von Externen)'},

    # MGV 2012
    82: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top02_Binnenrechtskommentar.pdf',
         'title': 'TOP02 Finanzierung des Binnenrechtskommentars'},
    83: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top03_Teilnahmebeitraege.pdf',
         'title': 'TOP03 Erstattung von Teilnahmebeiträgen'},
    84: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top04_Haertefallfoerderung.pdf',
         'title': 'TOP04 Änderung des § 5 MB-VM (Härtefallförderung)'},
    85: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top05_Schachmaterial.pdf',
         'title': 'TOP05 Beschaffung von Schachmaterial'},
    86: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top06_exPuls.pdf',
         'title': 'TOP06 Kosten exPuls'},
    88: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top01_Redaktionelle-Aenderungen.pdf',
         'title': 'TOP01 Redaktionelle Änderungen'},
    89: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'kassenpruefung_2012_klauser.pdf',
         'title': 'Kassenprüfung 2012 Klauser'},
    90: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'kassenpruefung_2012_keller.pdf',
         'title': 'Kassenprüfung 2012 Keller'},
    92: {'assembly_id': year_to_assembly_map[2012],
         'filename': 'mgv2012_top02a_Binnenrechtskommentar-Alternativantrag.pdf',
         'title': 'TOP02a Finanzierung des Binnenrechtskommentars (Alternativantrag)'},
    145: {'assembly_id': year_to_assembly_map[2012],
          'filename': 'mgv2012_protokoll.pdf',
          'title': 'Protokoll 2012'},

    # MGV 2013
    111: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top01_Vereinssitz.pdf',
          'title': 'TOP01 Änderung der Satzung (Vereinssitz) [Stand 05.11.13]'},
    112: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top02_Protokoll.pdf',
          'title': 'TOP02 Änderung der Satzung (Protokoll der MGV) [Stand 05.11.13]'},
    113: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top03_Praeferenzwahl-Abstimmungen.pdf',
          'title': 'TOP03 Präferenzwahlsystem bei Abstimmungen (Satzung) [Stand 05.11.13]'},
    115: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top05_Vereinsausgaben.pdf',
          'title': 'TOP05 Änderung MB-VM § 6 (Vereinsausgaben) [Stand 05.11.13]'},
    118: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top08_Vereinsaufnahme-1.pdf',
          'title': 'TOP08 Änderung MB zu § 4 Abs. 2 (Vereinsaufnahme (Teil 1)) [05.11.13]'},
    119: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top08_Vereinsaufnahme-2.pdf',
          'title': 'TOP08 Änderung MB zu § 4 Abs. 2 (Vereinsaufnahme (Teil 2)) [05.11.13]'},
    122: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top03_Praeferenzwahl-Wahlen.pdf',
          'title': 'MGV 2013 - 3. Präferenzwahlsystem bei Wahlen (Satzung) [Stand 15.11.13]'},
    124: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top07_Spenden-2.pdf',
          'title': 'MGV 2013 - 7. Änderung MB-VM § 7 (Spenden (Teil 2)) [Stand 18.11.13]'},
    125: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top03_Spenden-1.pdf',
          'title': 'MGV 2013 - 7. Änderung MB-VM § 7 (Spenden (Teil 1)) [Stand 20.11.13]'},
    126: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top04_Abstimmungsverfahren.pdf',
          'title': 'TOP04 MB Abstimmungsverfahren [Stand 21.11.13]'},
    127: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top16_Sockelzuschuesse.pdf',
          'title': 'TOP16 MB Sockelzuschüsse'},
    129: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top09_Noten.pdf',
          'title': 'TOP09 MB Anschaffung Noten'},
    130: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top09_Buttonmaschine.pdf',
          'title': 'TOP09 MB Anschaffung Buttonmaschine [Stand 25.11.]'},
    134: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'kassenpruefung_2013_klauser.pdf',
          'title': 'Kassenprüfung 2013 Klauser'},
    137: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top09_Multifunktionsgeraet.pdf',
          'title': 'TOP09 MB Anschaffung Multifunktionsgerät'},
    138: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top09_Ofen.pdf',
          'title': 'TOP09 MB Anschaffung Ofen/Mikrowellen-Kombination'},
    140: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top06_Haertefallfoerderung.pdf',
          'title': 'TOP06 Änderung MB-VM § 5 (Härtefallförderung) [Stand 25.11.13]'},
    141: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top09_Beamer.pdf',
          'title': 'TOP09 MB Anschaffung Beamer'},
    142: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_top07_Buergschaften.pdf',
          'title': 'TOP07 MB Buergschaften [Stand 25.11.]'},
    143: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'kassenpruefung_2013_kobitzsch.zip',
          'title': 'Kassenprüfung 2013 Kobitzsch'},
    146: {'assembly_id': year_to_assembly_map[2013],
          'filename': 'mgv2013_protokoll.pdf',
          'title': 'Protokoll 2013'},

    # MGV 2014
    150: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'kassenpruefung_2014_kobitzsch.pdf',
          'title': 'Kassenprüfung 2014 Kobitzsch'},
    151: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'kassenpruefung_2014_keller.pdf',
          'title': 'Kassenprüfung 2014 Keller'},
    154: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'kandidaten_2014.pdf',
          'title': 'Kandidaten 2014'},
    157: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'mgv2014_top01a_CdE-Ski.pdf',
          'title': 'TOP01a Änderung des MB-VM §3 (CdE-Ski)  [24.11.14]'},
    158: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'mgv2014_top01b_CdE-Segeln.pdf',
          'title': 'TOP01b Änderung des MB-VM §3 (CdE-Segeln) [24.11.14]'},
    163: {'assembly_id': year_to_assembly_map[2014],
          'filename': 'mgv2014_protokoll.pdf',
          'title': 'Protokoll 2014'},

    # MGV 2015
    166: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_05a_Cajon.pdf',
          'title': 'TOP05a MB Anschaffung eines Cajóns'},
    167: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top05b_Audiorekorder.pdf',
          'title': 'TOP05b MB Anschaffung eines Audiorekorders'},
    168: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top05c_.pdf',
          'title': 'TOP05c MB Anschaffung Tontechnik'},
    169: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top05d_Soundsystem.pdf',
          'title': 'TOP05d MB Anschaffung eines Soundsystems'},
    172: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'kassenpruefung_2015_kobitzsch.pdf',
          'title': 'Kassenprüfung 2015 Kobitzsch'},
    176: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top01_Aktivenforum.pdf',
          'title': 'TOP01 Änderung des MB-VM (Anhörung im Aktivenforum)'},
    183: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'kandidaten_2015.pdf',
          'title': 'Kandidaten 2015'},
    184: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top02_Haertefallfoerderung.pdf',
          'title': 'TOP02 Änderung MB-VM §5 (Härtefallförderung) [Stand 22.11.2015]'},
    185: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top04d_Spende.pdf',
          'title': 'TOP04d Spende an SchülerAkademien'},
    186: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top04a_Mitgliedsbeitrag.pdf',
          'title': 'TOP04a Anpassung des Mitgliedsbeitrags'},
    187: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top04b_Pruefauftrag.pdf',
          'title': 'TOP04b Allgemeiner Prüfauftrag zur Spende an DSA'},
    189: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top04c_Spende-via-Beitrag.pdf',
          'title': 'TOP04c SchülerAkademiezuschuss über Mitgliedsbeitrag'},
    190: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_top04a_Gegenantrag.pdf',
          'title': 'TOP04a Gegenantrag: Beibehaltung des Mitgliedsbeitrags'},
    192: {'assembly_id': year_to_assembly_map[2015],
          'filename': 'mgv2015_protokoll.pdf',
          'title': 'Protokoll 2015'},

    # MGV 2016
    197: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'mgv2016_top01_Vereinsausgaben.pdf',
          'title': 'TOP01 Änderung des MB VM §6 (Allgemeine '
                   'Vereinsausgaben)'},
    201: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'kassenpruefung_2016_kobitzsch.pdf',
          'title': 'Kassenprüfung 2016 Kobitzsch'},
    202: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'kassenpruefung_2016_blank.pdf',
          'title': 'Kassenprüfung 2016 Blank'},
    203: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'mgv2016_top03_AufnahmeAktivenforum.pdf',
          'title': 'TOP03 Änderung der Aufnahmeregelung in das Aktivenforum'},
    204: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'kandidaten_2016.pdf',
          'title': 'Kandidaten 2016'},
    206: {'assembly_id': year_to_assembly_map[2016],
          'filename': 'mgv2016_protokoll.pdf',
          'title': 'Protokoll 2016'},

    # MGV 2017
    208: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'mgv2017_top01_Zusammensetzung-Vorstand.pdf',
          'title': 'TOP01 Satzungsänderung §13 - Zusammensetzung des Vorstands'},
    209: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'mgv2017_top03_Beamer.pdf',
          'title': 'TOP03 Anschaffung von 3 neuen Beamern'},
    210: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'mgv2017_top02a_Aufnahmekriterium.pdf',
          'title': 'TOP02a Anpassung des MB zu §4 Abs. 2 der Satzung'},
    211: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'mgv2017_top02a_Aufnahmekriterium-MusikAka.pdf',
          'title': 'TOP02a Anpassung des MB zu §4 Abs. 2 der Satzung - MusikAkademie'},
    213: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'kanditaten_2017.pdf',
          'title': 'Kandidaten 2017'},
    216: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'kassenpruefung_2017_helmsauer.pdf',
          'title': 'Kassenprüfung 2017 Helmsauer'},
    220: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'kassenpruefung_2017_Blank.pdf',
          'title': 'Kassenprüfung 2017 Blank'},
    225: {'assembly_id': year_to_assembly_map[2017],
          'filename': 'mgv2017_protokoll.pdf',
          'title': 'Protokoll 2017'},
}

sorted_files = sorted(files.items(), key=lambda f: f[1]["filename"])
for file_id, file in sorted_files:
    pass
    # print(file_id)

for file_id, file in sorted_files:
    attachment = Path("/cdedb2/bin/cdefiles/download") / "{}.pdf".format(
        file_id)
    if attachment.exists():
        if file["title"] not in assembly.list_attachments(
                rs(DEFAULT_ID), assembly_id=file["assembly_id"]).values():
            if file["assembly_id"] not in assembly.list_assemblies(rs(DEFAULT_ID)):
                print("assembly {} does not exist".format(file["assembly_id"]))
                continue
            new_id = assembly.add_attachment(rs(DEFAULT_ID), file)
            new_path = assembly.conf["STORAGE_DIR"] / 'assembly_attachment' / str(
                new_id)
            shutil.copy(attachment, new_path)
        else:
            print(attachment, "already uploaded")
    else:
        print(attachment,
              "does not exist. This probably means that this was a zip-file.")
