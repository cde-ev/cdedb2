#!/usr/bin/env python3

"""Migrate the old dataset into the new database.

This assumes the following.

* The old dataset has been imported into a database named cdedbxy.

* A pristine copy of the new database cdb exists (with an empty ldap
  tree)

* The script is run by the www-data user (who has access to the
  configuration file containing the passwords).
"""

import collections
import datetime
import decimal
import gettext
import random
import re
import sys

import ldap3

import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

import pytz

from cdedb.backend.core import CoreBackend
from cdedb.backend.cde import CdEBackend
from cdedb.backend.past_event import PastEventBackend
from cdedb.backend.ml import MlBackend
from cdedb.backend.assembly import AssemblyBackend
from cdedb.database.connection import IrradiatedConnection

##
## definitions
##

DEFAULT_ID = 5124
LAST_EXPULS = 51

## WHITELIST
WHITELIST = {DEFAULT_ID}

## go through whole dataset with a window
OFFSET = None
for i in range(100000):
    if OFFSET is not None:
        WHITELIST.add(OFFSET + i)

## admin IDs
WHITELIST.add(568)
WHITELIST.add(5682)
WHITELIST.add(2158)
WHITELIST.add(1143)
WHITELIST.add(2718)
WHITELIST.add(1475)
WHITELIST.add(8177)
WHITELIST.add(4463)
WHITELIST.add(4063)
WHITELIST.add(5939)
WHITELIST.add(5936)
WHITELIST.add(8737)
WHITELIST.add(2187)
WHITELIST.add(4443)
WHITELIST.add(7311)
WHITELIST.add(11275)
WHITELIST.add(4114)
WHITELIST.add(10973)
WHITELIST.add(8586)
WHITELIST.add(51)
WHITELIST.add(10705)
WHITELIST.add(5843)
WHITELIST.add(12925)
WHITELIST.add(3915)
WHITELIST.add(8737)
WHITELIST.add(5782)
WHITELIST.add(10441)
WHITELIST.add(8565)
WHITELIST.add(16231)
WHITELIST.add(10848)
WHITELIST.add(8674)

# disable
WHITELIST = None

##
## Fixes for real world data
##
FIXES = {
    'postal_code': {
        '81939': '81929',
        '12345': '12347',
        '81627': '81675',
        '48179': '48149',
        '01052': '91052',
        '741638': '71638',
        '44314': '44135',
        '531115': '53115',
        '67336': '67663',
        '80938': '80939',
        '79103': '79104',
        '82778': '82278',
        '54202': '54292',
        '49252': '49525',
        '809393': '80939',
        '53199': '53119',
        '42879': '42897',
        '80631': '80634',
        '23912': '23911',
        '69129': '69120',
        '97047': '97074',
        '93153': '93053',
        '72974': '72074',
        '86516': '86156',
        '88619': '88630',
        '83175': '81375',
        '1057': '',
        '78646': '78464',
        '90939': '80939',
        '69621': '69126',
        '72139': '76139',
        '07443': '07743',
        '79018': '79108',
    },
    'postal_code2': {
        '35032': '35037',
        '50256': '50226',
        '91561': '91564',
        '12345': '67659',
        '79116': '79117',
        '60740': '66740',
        '81627': '81675',
        '32075': '37075',
        '88619': '88630',
        '70912': '70192',
        '69621': '69126',
    },
    'telephone': {
        '+49 (512) 576187': '',
        '+49 (6121) 54966511': '',
        '+49 (341) ...': '',
        '+49 (167) 8 37 32 444': '',
        '+49 (1801) 021135887': '',
        '+42 (0': '+420 (',
        '+049 (': '+49 (',
        '+49 (123) 8831694': '',
        '+49 (2492)': '+49 (2402)',
        '+49 (123) 456789': '',
    },
    'mobile': {
        '+49 (150) 56015985': '',
        '33689503745': '',
        '+49 (902) 223216': '',
        '+42 (0': '+420 (',
        '+25(0) ': '+250 ',
        '07540133352': '007540133352',
        '+49 (7540) 133352': '',
        '+49 (123) 86028510': '',
        '+49 999999999': '',
        '+49 (157) 6194734': '',
    },
}

##
## helpers
##

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

def ldap_bool(val):
    mapping = {
        True: 'TRUE',
        False: 'FALSE',
    }
    return mapping[val]

def now():
    return datetime.datetime.now(pytz.utc)

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


# Old to new
ATTR_MAP = {
    'username': 'username',
    'notes': 'notes',
    'mitglied': 'is_member',
    'vorname': 'given_names',
    'nachname': 'family_name',
    'titel': 'title',
    'geschlecht': 'gender',
    'geburtsdatum': 'birthday',
    'telefon': 'telephone',
    'mobiltelefon': 'mobile',
    'zusatz': 'address_supplement',
    'anschrift': 'address',
    'plz': 'postal_code',
    'ort': 'location',
    'land': 'country',
    'geburtsname': 'birth_name',
    'zusatz2': 'address_supplement2',
    'anschrift2': 'address2',
    'plz2': 'postal_code2',
    'ort2': 'location2',
    'land2': 'country2',
    'homepage': 'weblink',
    'lks': 'specialisation',
    'schulort': 'affiliation',
    'abi': 'timeline',
    'guthaben': 'balance',
}

##
## create connections
##
conn_string = "dbname=cdedbxy user=cdb_old password=987654321098765432109876543210 port=5432 host=localhost"
cdedbxy = psycopg2.connect(conn_string,
                           cursor_factory=psycopg2.extras.RealDictCursor)
cdedbxy.set_client_encoding("UTF8")

conn_string = "dbname=cdb user=cdb password=987654321098765432109876543210 port=5432 host=localhost"
cdb = psycopg2.connect(conn_string,
                       connection_factory=IrradiatedConnection,
                       cursor_factory=psycopg2.extras.RealDictCursor)
cdb.set_client_encoding("UTF8")

ldap_server = ldap3.Server("ldap://localhost")
def ldap():
    return ldap3.Connection(ldap_server, user="cn=root,dc=cde-ev,dc=de",
                            password="s1n2t3h4d5i6u7e8o9a0s1n2t3h4d5i6u7e8o9a0")

def rs(persona_id):
    return RequestState(persona_id, cdb)

##
## initialize core.personas and ldap
##

## select scope (existing personas)
query = "SELECT user_id FROM mitglieder"
persona_ids = tuple(e['user_id'] for e in query_all(cdedbxy, query, tuple()))
persona_ids = (DEFAULT_ID,) + tuple(sorted(x for x in persona_ids if x != DEFAULT_ID))
if WHITELIST:
    persona_ids = tuple(x for x in persona_ids if x in WHITELIST)

## import an initial dataset
ALL_EMAILS = set()
for persona_id in persona_ids:
    query = "SELECT * FROM changes WHERE user_id = %s ORDER BY cdate ASC LIMIT 1"
    initial = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM auth WHERE user_id = %s"
    auth = query_one(cdedbxy, query, (persona_id,))
    username = initial['username']
    if username in ALL_EMAILS:
        print("*** DOUBLE EMAIL: {}!".format(username))
        username = None
    elif username:
        ALL_EMAILS.add(username)
    data = {
        'id': persona_id,
        'username': username,
        ## slight modification of 'secret' (disables online password change)
        'password_hash': ("$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
                          "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHZ/si/"),
        'is_active': auth['active_account'],
        'is_admin': False,
        'is_core_admin': False,
        'is_cde_admin': False,
        'is_event_admin': False,
        'is_ml_admin': False,
        'is_assembly_admin': False,
        'is_cde_realm': True,
        'is_event_realm': True,
        'is_ml_realm': True,
        'is_assembly_realm': True,
        'is_searchable': initial['server_einwilligung'],
        'is_archived': False,
        'display_name': initial['vorname'],
        'name_supplement': None,
        'gender': None, # fixed below
        'interests': None,
        'free_form': None,
        'decided_search': initial['server_einwilligung'],
        'trial_member': False,
        'bub_search': False,
        'foto': None,
    }
    if initial['geschlecht'] == True:
        ## male
        data['gender'] = 2
    elif initial['geschlecht'] == False:
        ## female
        data['gender'] = 1
    else:
        ## other
        data['gender'] = 10
    for old, new in ATTR_MAP.items():
        if new not in data:
            data[new] = initial[old]
    data['fulltext'] = fulltext(data)
    insert(cdb, 'core.personas', data)
    ldap_data = {
        'sn': data['family_name'],
        'mail': username or '',
        ## slight modification of 'secret'
        'userPassword': "{SSHA}D5JG6KwFxs11jv0LnEmFSeBCjGrHCDWV",
        'cn': data['given_names'],
        'displayName': data['display_name'],
        'isActive': ldap_bool(data['is_active'])
    }
    dn = "uid={},ou=personas,dc=cde-ev,dc=de".format(persona_id)
    with ldap() as l:
        l.add(dn, object_class='cdePersona', attributes=ldap_data)
    data.update({
        'submitted_by': initial['who'],
        'reviewed_by': None,
        'ctime': now(),
        'generation': 1,
        'change_note': "Initial import.",
        'change_status': 2,
        'persona_id': persona_id
    })
    if not data['submitted_by']:
        data['submitted_by'] = DEFAULT_ID
    del data['id']
    del data['password_hash']
    del data['fulltext']
    insert(cdb, 'core.changelog', data)
    print("Added {} {} ({})".format(data['given_names'], data['family_name'],
                                    persona_id))

# Fix sequences
query = "SELECT setval('core.personas_id_seq', %s)"
query_exec(cdb, query, (max(persona_ids),))


##
## prepare backends
##
core = CoreBackend("/etc/cdedb-application-config.py")
cde = CdEBackend("/etc/cdedb-application-config.py")
past_event = PastEventBackend("/etc/cdedb-application-config.py")
ml = MlBackend("/etc/cdedb-application-config.py")
assembly = AssemblyBackend("/etc/cdedb-application-config.py")

##
## Import changelog
##
ERRORS = []
for persona_id in persona_ids:
    query = "SELECT * FROM changes WHERE user_id = %s"
    changes = query_all(cdedbxy, query, (persona_id,))
    changes = sorted(changes, key=lambda e: e['cdate'])
    previous = None
    current = None
    line = "Changelog for {} {} ({}):".format(
        changes[0]['vorname'], changes[0]['nachname'], persona_id)
    print(line, end="")
    last_skipped = False
    for num, change in enumerate(changes):
        if not previous:
            previous = change
            continue
        print(" {}".format(num), end="")
        current = change
        data = {
            'id': persona_id,
        }
        if current['username'] != previous['username']:
            if current['username'] not in ALL_EMAILS:
                data['username'] = current['username']
                ALL_EMAILS = ALL_EMAILS - {previous['username']}
        if current['server_einwilligung'] != previous['server_einwilligung']:
            data['is_searchable'] = current['server_einwilligung']
            data['decided_search'] = current['server_einwilligung']
        if current['geschlecht'] != previous['geschlecht']:
            if current['geschlecht'] == True:
                ## male
                data['gender'] = 2
            elif current['geschlecht'] == False:
                ## female
                data['gender'] = 1
            else:
                ## other
                data['gender'] = 10
        for old, new in ATTR_MAP.items():
            if new not in ('username', 'gender'):
                if current[old] != previous[old]:
                    data[new] = current[old]
                    if 'old' == 'vorname':
                        data['display_name'] = current[old]
        who = current['who'] or DEFAULT_ID
        if current['resolved'] == False:
            raise ValueError("Unresolved change!")
        if current['resolved'] is None:
            print("** SKIP **", end="")
            last_skipped = True
            ## Skip changes which were never published
            continue
        last_skipped = False
        modified = False
        if 'balance' in data:
            modified = True
            balance = data['balance']
            del data['balance']
            difference = current['guthaben'] - previous['guthaben']
            if (difference > decimal.Decimal("-2.50")
                    and difference < decimal.Decimal("2.50")):
                print("*** SMALL TRANSACTION ***", end="")
                code = 99
            elif difference > 0:
                code = 10
            elif difference == decimal.Decimal("-2.50"):
                code = 11
            else:
                print("*** STRANGE TRANSACTION ***", end="")
                code = 99
            core.change_persona_balance(rs(who), persona_id, balance, code)
        if 'username' in data:
            modified = True
            username = data['username']
            del data['username']
            core.change_username(rs(who), persona_id, username, None)
        if 'is_member' in data:
            modified = True
            is_member = data['is_member']
            del data['is_member']
            core.change_membership(rs(who), persona_id, is_member)
        if 'birthday' in data and data['birthday'] is None:
            del data['birthday']
        if len(data) > 1:
            modified = True
            for fix in FIXES:
                if data.get(fix):
                    for wrong, correct in FIXES[fix].items():
                        if data[fix].startswith(wrong):
                            print("*** FIX {} ***".format(fix), end="")
                            data[fix] = data[fix].replace(wrong, correct)
            if (data.get('address_supplement') == "Schweiz"
                    and "country" not in data):
                del data['address_supplement']
                data['country'] = "Schweiz"
            try:
                core.change_persona(
                    rs(who), data, change_note=change['changes'])
            except:
                if ERRORS is not None:
                    ERRORS.append((sys.exc_info(), data['id']))
                else:
                    raise
        if not modified:
            print("** SAME **", end="")
        previous = current
    if last_skipped:
        print("*** SKIPPED FINAL CHANGE ***")
    print()
if ERRORS:
    print("****")
    print("**** ERRORS ****")
    print("****")
    print(ERRORS)

##
## Import event history
##

## Prepare instutions
INSTITUTION_MAP = {}
new_id = past_event.create_institution(
    rs(DEFAULT_ID), {'title': "Club der Ehemaligen", 'moniker': "CdE"})
INSTITUTION_MAP[0] = new_id
new_id = past_event.create_institution(
    rs(DEFAULT_ID), {'title': "Deutsche SchülerAkademie", 'moniker': "DSA"})
INSTITUTION_MAP[1] = new_id
new_id = past_event.create_institution(
    rs(DEFAULT_ID), {'title': "Deutsche JuniorAkademie", 'moniker': "DJA"})
INSTITUTION_MAP[2] = new_id
new_id = past_event.create_institution(
    rs(DEFAULT_ID), {'title': "Jugendbildung in Gesellschaft und Wissenschaft",
                     'moniker': "JGW"})
INSTITUTION_MAP[3] = new_id

## Import events
EVENT_MAP = {}
WINTER_AKA_MAP = {}
query = "SELECT * FROM veranstaltungen"
events = query_all(cdedbxy, query, tuple())
events = tuple(sorted(events, key=lambda e: e['shortname']))
for event in events:
    split_name = None
    if 'Winter' in event['name'] or 'Musik' in event['name']:
        ## Deduplicate WinterAkademie and MusikAkademie
        split_name = ' '.join(event['name'].split()[:2])
        if split_name in SPLIT_AKA_MAP:
            EVENT_MAP[event['id']] = SPLIT_AKA_MAP[split_name]
            print("*** Deduplicated event {} ***".format(event['name']))
            continue
    new = {
        'title': split_name or event['name'],
        'shortname': event['shortname'],
        'institution': INSTITUTION_MAP[event['organisator']],
        'description': None,
    }
    mo = re.search('[^0-9]([0-9]{4})([^0-9]|$)', new['title'])
    if not mo:
        print("*** NO YEAR *** {}".format(new['title']))
        year = 2000
    else:
        year = int(mo.group(1))
    new['tempus'] = datetime.date(year, 7, 1)
    new_id = past_event.create_past_event(rs(DEFAULT_ID), new)
    EVENT_MAP[event['id']] = new_id
    if split_name:
        SPLIT_AKA_MAP[split_name] = new_id
    print("Created event in {} -- {}".format(new['tempus'].year, new['title']))

## Import courses
COURSE_MAP = {}
COURSE_COMBINATIONS = {}
ORGA_COURSES = set()
for event_id in EVENT_MAP:
    query = "SELECT * FROM veranstaltungen WHERE id = %s"
    event = query_one(cdedbxy, query, (event_id,))
    print("Creating courses for {} -- ".format(event['shortname']), end="")
    query = "SELECT * FROM veranstaltungen_kurse WHERE v_id = %s"
    courses = query_all(cdedbxy, query, (event_id,))
    courses = sorted(courses, key=lambda e: e['kurs_nr'])
    for course in courses:
        new = {
            'pevent_id': EVENT_MAP[course['v_id']],
            'nr': course['kurs_nr'],
            'title': course['kurs_name'],
            'description': None,
        }
        if 'Orga' in course['kurs_name'] and 'Organ' not in course['kurs_name']:
            ORGA_COURSES.add(course['id'])
            print(" **ORGA**", end="")
            continue
        ident = (new['pevent_id'], new['nr'])
        printprefix = ""
        if ident in COURSE_COMBINATIONS:
            ## This can happen in case of deduplicated split academies
            COURSE_MAP[course['id']] = COURSE_COMBINATIONS[ident]
            printprefix = "*DUP*"
        else:
            new_id = past_event.create_past_course(rs(DEFAULT_ID), new)
            COURSE_MAP[course['id']] = new_id
            COURSE_COMBINATIONS[ident] = new_id
        nr = new['nr'] or '.'
        print(" {}{}".format(printprefix, nr), end="")
    print()

## Import participants
events = {e['id']: e for e in events}
PARTICIPANT_COMBINATIONS = set()
for persona_id in persona_ids:
    persona = core.get_personas(rs(DEFAULT_ID), (persona_id,))[persona_id]
    print("Events for {} {} ({}) -- ".format(
        persona['given_names'], persona['family_name'], persona_id), end="")
    query = "SELECT * FROM veranstaltungen_teilnehmer WHERE user_id = %s"
    participations = query_all(cdedbxy, query, (persona_id,))
    participations = sorted(participations, key=lambda p: p['v_id'])
    for participant in participations:
        is_orga = False
        if participant['kurs_id'] is not None:
            if participant['kurs_id'] in ORGA_COURSES:
                course = None
                is_orga = True
            else:
                course = COURSE_MAP[participant['kurs_id']]
        else:
            course = None
        ident = (EVENT_MAP[participant['v_id']], course, persona_id, is_orga)
        printprefix = ""
        if ident in PARTICIPANT_COMBINATIONS:
            ## This can mainly happen for deduplicated split academies
            printprefix = "*DUP*"
        else:
            past_event.add_participant(
                rs(DEFAULT_ID), EVENT_MAP[participant['v_id']], course, persona_id,
                is_instructor=False, is_orga=is_orga)
            PARTICIPANT_COMBINATIONS.add(ident)
        print(" {}{}".format(printprefix, events[participant['v_id']]['shortname']), end="")
    print()

##
## initialize bookkeeping information
##
query = "SELECT * FROM semester"
semesters = query_all(cdedbxy, query, tuple())
last_semester = max(s['next_expuls'] for s in semesters)
insert(cdb, "cde.org_period", {
    'id': last_semester + 1,
    'billing_state': None,
    'billing_done': None,
    'ejection_state': None,
    'ejection_done': None,
    'balance_state': None,
    'balance_done': None,
})
insert(cdb, "cde.expuls_period", {
    'id': LAST_EXPULS + 1,
    'addresscheck_state': None,
    'addresscheck_done': None,
})

##
## lastschriften
##

LASTSCHRIFT_MAP = {}
for persona_id in persona_ids:
    persona = core.get_personas(rs(DEFAULT_ID), (persona_id,))[persona_id]
    query = "SELECT * FROM lastschrift WHERE user_id = %s"
    lastschrifts = query_all(cdedbxy, query, (persona_id,))
    if not lastschrifts:
        continue
    lastschrifts = sorted(lastschrifts, key=lambda l: l['erteilt'])
    print("Lastschrift for {} {} ({}) --".format(
        persona['given_names'], persona['family_name'], persona_id), end="")
    for lastschrift in lastschrifts:
        query = "SELECT * FROM lastschrift_bankdaten WHERE lastschrift_id = %s"
        bank = query_one(cdedbxy, query, (lastschrift['id'],))
        if lastschrift['widerrufen']:
            phrase = "[{} bis {}]".format(lastschrift['erteilt'].date(), lastschrift['widerrufen'].date())
        else:
            phrase = "{}".format(lastschrift['erteilt'].date())
        print(" {}".format(phrase), end="")
        if not bank['iban']:
            print("*** NO IBAN ***", end="")
            continue
        new = {
            'persona_id': lastschrift['user_id'],
            'amount': lastschrift['betrag'],
            'max_dsa': lastschrift['max_dsa'],
            'iban': bank['iban'],
            'account_owner': bank['kontoinhaber'],
            'account_address': bank['anschrift'],
            'granted_at': lastschrift['erteilt'],
            'revoked_at': lastschrift['widerrufen'],
            'notes': lastschrift['kommentar'],
        }
        new_id = cde.create_lastschrift(rs(lastschrift['who']), new)
        LASTSCHRIFT_MAP[lastschrift['id']] = new_id
    print()

## Do not import transactions since we don't import semesters

##
## mailinglists
##

## Import lists
MAILINGLIST_MAP = {}
query = "SELECT * FROM mailinglist"
lists = query_all(cdedbxy, query, tuple())
lists = tuple(sorted(lists, key=lambda l: l['id']))
for alist in lists:
    if alist['inactive'] or alist['list_type'] == 10:
        continue
    new = {
        'title': alist['listname'],
        'address': alist['address'],
        'description': None,
        'subject_prefix': alist['prefix'],
        'maxsize': alist['maxsize'],
        'is_active': True,
        'notes': None,
        'gateway': None,
        'event_id': None,
        'registration_stati': tuple(),
        'assembly_id': None,
    }
    if alist['opt_in'] == True and alist['mod_sub'] == True:
        new['sub_policy'] = 4
    elif alist['opt_in'] == True and alist['mod_sub'] == False:
        new['sub_policy'] = 3
    elif alist['opt_in'] == True and alist['mod_sub'] is None:
        new['sub_policy'] = 5
    elif alist['opt_in'] == False:
        new['sub_policy'] = 2
    elif alist['opt_in'] == None:
        new['sub_policy'] = 1
    else:
        raise ValueError("Impossible!")
    if alist['mod_umessages']:
        new['mod_policy'] = 3
    elif alist['mod_messages']:
        new['mod_policy'] = 2
    else:
        new['mod_policy'] = 1
    if alist['mime'] == True:
        new['attachment_policy'] = 3
    elif alist['mime'] == False:
        new['attachment_policy'] = 2
    elif alist['mime'] is None:
        new['attachment_policy'] = 1
    else:
        raise ValueError("Impossible!")
    if alist['cde_only']:
        new['audience_policy'] = 4
    elif "@aka.cde-ev.de" in alist['address']:
        new['audience_policy'] = 3
    elif alist['address'].startswith("mgv"):
        new['audience_policy'] = 2
    else:
        new['audience_policy'] = 1
    new_id = ml.create_mailinglist(rs(DEFAULT_ID), new)
    MAILINGLIST_MAP[alist['id']] = new_id
    print("Created mailinglist {}".format(new['address']))

## Import subscribers
for list_id in MAILINGLIST_MAP:
    query = "SELECT * FROM mailinglist WHERE id = %s"
    alist = query_one(cdedbxy, query, (list_id,))
    query = "SELECT * FROM mailinglist_subscriber WHERE ml_id = %s"
    subs = query_all(cdedbxy, query, (list_id,))
    subs = tuple(sorted(subs, key=lambda s: (s['user_id'] or 1)))
    print("Adding subscribers for {} -- ".format(alist['address']), end="")
    if alist['event_id']:
        query = (
            "SELECT users.cdedb_id AS user_id, FALSE as is_request, "
            " FALSE as is_whitelist, FALSE as user_is_mod, NULL as address "
            " FROM events.registration JOIN events.users "
            " ON registration.user_id = users.id "
            " WHERE registration.event_id = %s AND registration.status = 1")
        subs = query_all(cdedbxy, query, (alist['event_id'],))
        subs = tuple(sorted(subs, key=lambda s: (s['user_id'] or 1)))
        print("** EVENT **", end="")
    elif not alist['opt_in']:
        print("** SKIPPING OPT-OUT **")
        continue
    for sub in subs:
        if WHITELIST and sub['user_id'] not in WHITELIST:
            continue
        if not sub['user_id'] or sub['is_request'] or sub['is_whitelist']:
            continue
        ml.change_subscription_state(
            rs(DEFAULT_ID), MAILINGLIST_MAP[list_id], sub['user_id'],
            subscribe=True, address=sub['address'])
        print(" {}".format(sub['user_id']), end="")
        if sub['user_is_mod']:
            new_id = MAILINGLIST_MAP[list_id]
            current = ml.get_mailinglists(rs(DEFAULT_ID), (new_id,))[new_id]
            update = {
                'id': new_id,
                'moderators': current['moderators'] | {sub['user_id']},
            }
            ml.set_mailinglist(rs(DEFAULT_ID), update)
            print("##", end="")
    print()

##
## assemblies
##

## Import assemblies
ASSEMBLY_MAP = {}
query = "SELECT * FROM assembly"
assemblies = query_all(cdedbxy, query, tuple())
assemblies = tuple(sorted(assemblies, key=lambda l: l['id']))
for anassembly in assemblies:
    new = {
        'title': anassembly['name'],
        'description': "Alte Versammlung",
        'signup_end': now(),
        'is_active': True,
        'notes': None,
    }
    new_id = assembly.create_assembly(rs(DEFAULT_ID), new)
    ASSEMBLY_MAP[anassembly['id']] = new_id
    print("Created assembly {}".format(new['title']))

## Import ballots
BALLOT_MAP = {}
for assembly_id in ASSEMBLY_MAP:
    query = "SELECT * FROM assembly WHERE id = %s"
    theassembly = query_one(cdedbxy, query, (assembly_id,))
    query = "SELECT * FROM vote_ballots WHERE assembly = %s"
    ballots = query_all(cdedbxy, query, (assembly_id,))
    ballots = tuple(sorted(ballots, key=lambda b: b['agenda_item']))
    print("Adding ballots for {} -- ".format(theassembly['name']), end="")
    for ballot in ballots:
        query = "SELECT * FROM vote_options WHERE ballot_id = %s"
        candidates = query_all(cdedbxy, query, (ballot['id'],))
        candidates = tuple(sorted(candidates, key=lambda c: c['id']))
        newcandidates = {
            -(i+1): {
                'description': c['opt_name'],
                'moniker': str(i+1)
            }
            for i, c in enumerate(candidates)
        }
        quorum = round(ballot['max_members'] * ballot['quorum'] / 100)
        new = {
            'assembly_id': ASSEMBLY_MAP[assembly_id],
            'use_bar': True,
            'candidates': newcandidates,
            'description': ballot['description'],
            'notes': ballot['agenda_item'],
            'quorum': quorum,
            'title': ballot['name'],
            'vote_begin': ballot['starttime'],
            'vote_end': ballot['deadline'],
            'vote_extension_end': ballot['deadline_q'],
            'votes': 0
        }
        new_id = assembly.create_ballot(rs(DEFAULT_ID), new)
        BALLOT_MAP[ballot['id']] = new_id
        print(" {}".format(ballot['agenda_item']), end="")
    print()

## Make attendees
for assembly_id in ASSEMBLY_MAP:
    insert(cdb, "assembly.attendees", {
        'persona_id': DEFAULT_ID,
        'assembly_id': ASSEMBLY_MAP[assembly_id],
        'secret': None,
    })

## Import results
for ballot_id in BALLOT_MAP:
    query = "SELECT * FROM vote_ballots WHERE id = %s"
    ballot = query_one(cdedbxy, query, (ballot_id,))
    query = "SELECT * FROM assembly WHERE id = %s"
    theassembly = query_one(cdedbxy, query, (ballot['assembly'],))
    query = "SELECT * FROM votes WHERE ballot_id = %s"
    votes = query_all(cdedbxy, query, (ballot_id,))
    tally = collections.defaultdict(lambda: 0)
    for vote in votes:
        if vote['option_id']:
            tally[vote['option_id']] += 1
    query = "SELECT * FROM vote_options WHERE ballot_id = %s"
    candidates = query_all(cdedbxy, query, (ballot['id'],))
    for candidate in candidates:
        # Make sure all candidates are present in the defaultdict
        _ = tally[candidate['id']]
    moniker_map = {key: str(i+1) for i, key in enumerate(sorted(tally))}
    ranking = tuple(reversed(sorted((v, k) for k, v in tally.items())))
    rawvote = tuple(moniker_map[option] for _, option in ranking)
    barvote = rawvote[:ballot['votes']] + ('_bar_',) + rawvote[ballot['votes']:]
    vote = '>'.join(barvote)
    print("Adding result for {} -- {}".format(ballot['name'], vote))
    insert(cdb, "assembly.voter_register", {
        'persona_id': DEFAULT_ID,
        'ballot_id': BALLOT_MAP[ballot_id],
        'has_voted': True,
    })
    insert(cdb, "assembly.votes", {
        'ballot_id': BALLOT_MAP[ballot_id],
        'vote': vote,
        'salt': 'None',
        'hash': 'None',
    })

## Conclude assemblies
print("Concluding assemblies")
query = "UPDATE assembly.assemblies SET is_active = False"
query_exec(cdb, query, tuple())

##
## grant admin privileges and reset password
##
core.change_admin_bits(rs(DEFAULT_ID), {
    'id': DEFAULT_ID,
    'is_admin': True,
    'is_core_admin': True,
    'is_cde_admin': True,
    'is_event_admin': True,
    'is_ml_admin': True,
    'is_assembly_admin': True,
    })
query = "UPDATE core.personas SET password_hash = %s WHERE id = %s"
query_exec(cdb, query, ('$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/', DEFAULT_ID))

##
## consistency checks
##
ATTR_MAP['akademie'] = 'akademie'

def deviation(key, dataset, old_value):
    print("*** DEVIATION ({}) *** for {} {} ({}) -- old: {} -- new: {}".format(
        key, dataset['given_names'], dataset['family_name'], dataset['id'],
        old_value, dataset[key]))

for persona_id in persona_ids:
    query = "SELECT * FROM mitglieder WHERE user_id = %s"
    old_member = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM auth WHERE user_id = %s"
    old_auth = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM adressen WHERE user_id = %s AND is_primary = TRUE"
    old_address = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM adressen WHERE user_id = %s AND is_primary = FALSE"
    old_address2 = query_one(cdedbxy, query, (persona_id,))
    infos = past_event.participation_infos(rs(DEFAULT_ID), (persona_id,))
    aka = min(infos[persona_id], key=lambda e: e['tempus'], default=None)
    if aka:
        pevent_id = aka['pevent_id']
        aka = past_event.get_past_events(rs(DEFAULT_ID), (pevent_id,))
        aka = aka[pevent_id]['shortname']
    old_address = old_address or {}
    old_address2 = old_address2 or {}
    new = core.get_total_personas(rs(DEFAULT_ID), (persona_id,))[persona_id]
    if old_member['mitglied'] != new['is_member']:
        core.change_membership(rs(DEFAULT_ID), persona_id,
                               old_member['mitglied'])
        print("*** FIX membership *** {} {} ({}) -- now {}".format(
            new['given_names'], new['family_name'], new['id'],
            old_member['mitglied']))
    if old_auth['username'] != new['username']:
        if (old_auth['username'] and new['username']
                and old_auth['username'].lower() == new['username'].lower()):
            ## Skip capitalization changes
            continue
        deviation('username', new, old_auth['username'])
    if old_auth['active_account'] != new['is_active']:
        deviation('is_active', new, old_auth['active_account'])
    if old_member['server_einwilligung'] != new['is_searchable']:
        deviation('is_searchable', new, old_member['server_einwilligung'])
    if old_member["geschlecht"] == True:
        if new["gender"] != 2:
            deviation("gender", new, old_member["geschlecht"])
    elif old_member["geschlecht"] == False:
        if new["gender"] != 1:
            deviation("gender", new, old_member["geschlecht"])
    elif old_member["geschlecht"] == None:
        if new["gender"] != 10:
            deviation("gender", new, old_member["geschlecht"])
    else:
        deviation("gender", new, old_member["geschlecht"])
    new['akademie'] = aka
    for attr in ("nachname", "vorname", "titel", "geburtsname", "telefon",
                 "mobiltelefon", "homepage", "lks", "schulort", "abi",
                 "geburtsdatum", "guthaben", "notes", "akademie"):
        if old_member[attr] != new[ATTR_MAP[attr]]:
            if (attr in ("telefon", "mobiltelefon")
                    and old_member[attr] and new[ATTR_MAP[attr]]):
                if ([d for d in old_member[attr] if d.isdigit()]
                        == [d for d in new[ATTR_MAP[attr]] if d.isdigit()]):
                    ## Skip reformatted telephone numbers
                    continue
            if (isinstance(old_member[attr], str)
                    and isinstance(new[ATTR_MAP[attr]], str)
                    and old_member[attr].strip() == new[ATTR_MAP[attr]].strip()):
                ## Skip whitespace changes
                continue
            if attr == "notes":
                ## This is borked in the old database
                continue
            if attr == "akademie" and old_member[attr] is None:
                ## Skip newly recognized academies
                continue
            deviation(ATTR_MAP[attr], new, old_member[attr])
    for attr in ("zusatz", "anschrift", "plz", "ort", "land",):
        if old_address.get(attr) != new[ATTR_MAP[attr]]:
            deviation(ATTR_MAP[attr], new, old_address.get(attr))
    for attr in ("zusatz", "anschrift", "plz", "ort", "land",):
        if old_address2.get(attr) != new[ATTR_MAP[attr+"2"]]:
            deviation(ATTR_MAP[attr+"2"], new, old_address2.get(attr))
