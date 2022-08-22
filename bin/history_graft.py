#!/usr/bin/env python3

"""Migrate additional information from the old dataset into the new database.

This assumes the following.

* The old dataset has been imported into a database named cdedbxy.

* The new database cdb exists and a special user cdb_graft has the necessary
  permissions to do the desired modifications.
"""

import collections
import copy
import datetime
import decimal
import zoneinfo

import psycopg2
import psycopg2.extensions
import psycopg2.extras

psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

DEFAULT_ID = 5124
WINDOW = range(1, 27000)

#
# Fixes for real world data
#
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
            return list(x for x in cur.fetchall())


def sql_update(sql, table, data):
    id = data.pop('id')
    keys = tuple(data.keys())
    query = "UPDATE {table} SET {setters} WHERE id = %s"
    query = query.format(
        table=table, setters=", ".join(f'{key} = %s' for key in keys))
    params = tuple(data[key] for key in keys) + (id,)
    query_exec(sql, query, params)


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
    'cdate': 'ctime',
}

#
# create connections
#
conn_string = "dbname=cdedbxy user=cdb_old password=12345678909876543210123456789 port=5432 host=localhost"
cdedbxy = psycopg2.connect(conn_string,
                           cursor_factory=psycopg2.extras.RealDictCursor)
cdedbxy.set_client_encoding("UTF8")

conn_string = "dbname=cdb user=cdb_graft password=12345678909876543210123456789 port=5432 host=localhost"
cdb = psycopg2.connect(conn_string,
                       cursor_factory=psycopg2.extras.RealDictCursor)
cdb.set_client_encoding("UTF8")

#
# retrieve old dataset
#

# select scope (existing personas)
query = "SELECT user_id FROM mitglieder"
persona_ids = sorted(e['user_id'] for e in query_all(cdedbxy, query, tuple()))
persona_ids = tuple(pid for pid in persona_ids if not WINDOW or pid in WINDOW)

# import an initial dataset
ALL_EMAILS = set()
OLD_CHANGES = collections.defaultdict(list)
for persona_id in persona_ids:
    query = "SELECT * FROM changes WHERE user_id = %s ORDER BY cdate ASC LIMIT 1"
    initial = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM auth WHERE user_id = %s"
    auth = query_one(cdedbxy, query, (persona_id,))
    username = initial['username']
    if username in ALL_EMAILS:
        username = None
    elif username:
        ALL_EMAILS.add(username)
    data = {
        'persona_id': persona_id,
        'username': username,
        'is_active': auth['active_account'],
        'is_meta_admin': False,
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
        'gender': None,  # fixed below
        'interests': None,
        'free_form': None,
        'decided_search': initial['server_einwilligung'],
        'trial_member': False,
        'bub_search': False,
        'foto': None,
    }
    if initial['geschlecht'] is True:
        # male
        data['gender'] = 2
    elif initial['geschlecht'] is False:
        # female
        data['gender'] = 1
    else:
        # other
        data['gender'] = 10
    for old, new in ATTR_MAP.items():
        if new not in data:
            data[new] = initial[old]
    data.update({
        'submitted_by': initial['who'],
        'reviewed_by': None,
        'change_note': "Initial import.",
        'change_status': 2,
        'affects_finance': False,
        'finance_code': None,
    })
    if not data['submitted_by']:
        data['submitted_by'] = DEFAULT_ID
    OLD_CHANGES[persona_id].append(data)
    print("Added {} {} ({})".format(data['given_names'], data['family_name'],
                                    persona_id))

# Import old changelog
for persona_id in persona_ids:
    query = "SELECT * FROM mitglieder WHERE user_id = %s"
    mitglied = query_one(cdedbxy, query, (persona_id,))
    query = "SELECT * FROM changes WHERE user_id = %s ORDER BY cdate"
    changes = query_all(cdedbxy, query, (persona_id,))
    previous = None
    current = None
    line = "Old changelog for {} {} ({}):".format(
        changes[0]['vorname'], changes[0]['nachname'], persona_id)
    print(line, end="")
    last_skipped = False
    if mitglied['mitglied'] and not changes[-1]['mitglied']:
        # fix inconsistency of old dataset
        changes.append(copy.deepcopy(dict(changes[-1])))
        changes[-1]['mitglied'] = True
        changes[-1]['cdate'] += datetime.timedelta(microseconds=1)
        changes[-1]['who'] = DEFAULT_ID
        print(" MFIX", end="")
    for num, change in enumerate(changes):
        if not previous:
            previous = change
            continue
        print(" {}".format(num), end="")
        current = change
        data = {
            'persona_id': persona_id,
        }
        if current['username'] != previous['username']:
            if current['username'] not in ALL_EMAILS:
                data['username'] = current['username']
                ALL_EMAILS = ALL_EMAILS - {previous['username']}
        if current['server_einwilligung'] != previous['server_einwilligung']:
            data['is_searchable'] = current['server_einwilligung']
            data['decided_search'] = current['server_einwilligung']
        if current['geschlecht'] != previous['geschlecht']:
            if current['geschlecht'] is True:
                # male
                data['gender'] = 2
            elif current['geschlecht'] is False:
                # female
                data['gender'] = 1
            else:
                # other
                data['gender'] = 10
        for old, new in ATTR_MAP.items():
            if new not in ('username', 'gender'):
                if current[old] != previous[old]:
                    data[new] = current[old]
                    if 'old' == 'vorname':
                        data['display_name'] = current[old]
        who = current['who'] or DEFAULT_ID
        if current['resolved'] is False:
            raise ValueError("Unresolved change!")
        if current['resolved'] is None:
            print("** SKIP **", end="")
            last_skipped = True
            # Skip changes which were never published
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
            OLD_CHANGES[persona_id].append({
                'persona_id': persona_id,
                'balance': balance,

                'ctime': data['ctime'],
                'submitted_by': who,
                'reviewed_by': None,
                'change_note': "Unspecified change.",
                'change_status': 2,
                'affects_finance': True,
                'finance_code': code,
            })
        if 'username' in data:
            modified = True
            username = data['username']
            del data['username']
            OLD_CHANGES[persona_id].append({
                'persona_id': persona_id,
                'username': username,

                'ctime': data['ctime'],
                'submitted_by': who,
                'reviewed_by': None,
                'change_note': "Emailadresse modifiziert.",
                'change_status': 2,
                'affects_finance': False,
                'finance_code': None,
            })
        if 'is_member' in data:
            modified = True
            is_member = data['is_member']
            del data['is_member']

            OLD_CHANGES[persona_id].append({
                'persona_id': persona_id,
                'is_member': is_member,

                'ctime': data['ctime'],
                'submitted_by': who,
                'reviewed_by': None,
                'change_note': "Mitgliedschaftsstatus geändert.",
                'change_status': 2,
                'affects_finance': True,
                'finance_code': 2 if is_member else 3,
            })
        if 'birthday' in data and data['birthday'] is None:
            del data['birthday']
        if len(data) > 2:
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
            data.update({
                'submitted_by': who,
                'reviewed_by': None,
                'change_note': change['changes'],
                'change_status': 2,
                'affects_finance': False,
                'finance_code': None,
            })
            OLD_CHANGES[persona_id].append(data)
        if not modified:
            print("** SAME **", end="")
        previous = current
    if last_skipped:
        print("*** SKIPPED FINAL CHANGE ***")
    print()

# Gather information about lastschrifts
query = "SELECT * FROM lastschrift ORDER BY erteilt ASC"
data = query_all(cdedbxy, query, tuple())
LASTSCHRIFTS = collections.defaultdict(list)
for entry in data:
    LASTSCHRIFTS[entry['user_id']].append(entry)

#
# Adjust new dataset
#

MIGRATION_TIME = datetime.datetime(2019, 3, 3, 3, 3,
                                   tzinfo=zoneinfo.ZoneInfo('Europe/Berlin'))


class Missing():
    def __str__(self):
        return "-- MISSING --"

    def __repr__(self):
        return "-- MISSING --"

    def __eq__(self, o):
        # Nasty hack to suppress noisy errors
        return True


MISSING = Missing()


def diff_changes(new, old):
    ret = {}
    if old is None:
        return ret
    irrelevant_keys = {
        'ctime', 'submitted_by', 'change_note', 'affects_finance', 'finance_code',
        'id', 'generation',

    }
    for key in new:
        if key not in irrelevant_keys:
            if new[key] != old.get(key, MISSING):
                ret[key] = (old.get(key, MISSING), new[key])
    return ret


def compare_datum(new, old, additional_suppress=set()):
    suppress = {
        # finicky values which undergo automatic adjustments
        'mobile', 'telephone',
        # new keys not present in old data
        'id', 'generation', 'is_cdelokal_admin', 'is_purged', 'is_auditor',
        'is_finance_admin', 'automated_change', 'code', 'paper_expuls',
        # synthetic keys
        'change_status', 'affects_finance', 'finance_code',
        # time is different (which is the whole point of this excercise
        'ctime',
    } | additional_suppress
    relevant_keys = (set(new) & set(old)) - suppress
    exceptions = {
        'change_note': {
            ('Username change.', 'Emailadresse modifiziert.'),  # translation
        },
        'birthday': {
            ('0001-01-01', 'None'),  # basically the same
        },
        'postal_code2': {
            ('69126', ' 69126')
        },
        'postal_code': {
            ('69126', ' 69126')
        },
    }
    for key in relevant_keys:
        if new.get(key) != old.get(key):
            if (str(new.get(key)), str(old.get(key))) in exceptions.get(key, set()):
                continue
            if {new.get(key), old.get(key)} == {None, ''}:
                continue
            if key == 'username':
                if ((str(new.get(key)).lower() == str(old.get(key)).lower())
                        or (new.get(key) is None
                            and new['change_note'] == 'Initial import.')
                        or (str(new.get(key)).startswith('(None, ')
                            and new[key][1] == old[key][1])):
                    continue
            if (key == 'birthday'
                    and str(new.get(key)).startswith('(datetime.date(1, 1, 1), ')
                    and str(old.get(key)).startswith('(None, ')):
                continue
            return False
    return True


# Use one transaction to make things atomic
with cdb as cdb_conn:

    # Update new changelog
    ARCHIVED_PERSONAS = set()
    NEWLY_INTRODUCED_CHANGES = collections.defaultdict(list)
    SKIPPED_CHANGES = collections.defaultdict(list)
    for persona_id in persona_ids:
        query = "SELECT * FROM core.changelog WHERE persona_id = %s ORDER BY id"
        changes = query_all(cdb_conn, query, (persona_id,))
        line = "New changelog for {} {} ({}):".format(
            changes[0]['given_names'], changes[0]['family_name'], persona_id)
        print(line, end="")
        if changes[0]['is_archived'] or changes[-1]['is_archived']:
            ARCHIVED_PERSONAS.add(persona_id)
            print(" archived")
            continue

        old_changes = OLD_CHANGES[persona_id]
        candidate_old = 0
        for change, previous in zip(changes, [None] + changes):
            if change['ctime'] > MIGRATION_TIME:
                break
            if ((change['change_note'] == 'Admin-Privilegien geändert.')):
                # Newly introduced change not present in old data
                print(f' [{change["generation"]}->NEW]', end="")
                NEWLY_INTRODUCED_CHANGES[persona_id].append(candidate_old)
                continue
            diff = diff_changes(change, previous)
            retry = True
            while retry:
                retry = False
                old_change = old_changes[candidate_old]
                old_previous = ([None] + old_changes)[candidate_old]
                old_diff = diff_changes(old_change, old_previous)
                if compare_datum(change, old_change) and compare_datum(diff, old_diff):
                    print(f' [{change["generation"]}->{old_change["ctime"]}]', end="")
                    update = {'id': change['id'], 'ctime': old_change['ctime']}
                    sql_update(cdb_conn, 'core.changelog', update)
                    candidate_old += 1
                else:
                    # telephone numbers and email addresses are normalized in the new db
                    # finance_code 99 is for edge cases which cause trouble
                    # lot's of finance_code 11 were swallowed, don't annotating them manually
                    # this is rather safe as we check for completeness later on
                    current_idx = changes.index(change)
                    if ((old_change['change_note'] == 'Telefonnummer: Format-Korrektur')
                            or (old_change['finance_code'] == 99)
                            or (old_change['change_note'] == 'Emailadresse modifiziert.')
                            or (old_change['change_note'] == 'Unspecified change.'
                                and old_change['finance_code'] == 11)
                            or (len(changes) > current_idx + 1
                                and (changes[current_idx + 1]['change_note']
                                     == 'Repariere Zweitadresse nach Migration'))
                            # these last four ones were somehow drop during migration
                            # for no discernible reason
                            or (persona_id == 8610 and candidate_old == 9)  # telephone
                            or (persona_id == 15811 and candidate_old == 27)  # address
                            or (persona_id == 16582 and candidate_old == 25)  # address
                            or (persona_id == 23541 and candidate_old == 7)):  # address
                        retry = True
                        print('** SKIP **', end="")
                        SKIPPED_CHANGES[persona_id].append(candidate_old)
                        candidate_old += 1
                        continue
                    else:
                        raise RuntimeError('Unmatched change!')
        if candidate_old == len(old_changes):
            print(" OK", end="")
        else:
            raise RuntimeError('Unconsumed changes!')
        print()

    # Update new core log
    for persona_id in persona_ids:
        query = "SELECT * FROM core.log WHERE persona_id = %s ORDER BY id"
        changes = query_all(cdb_conn, query, (persona_id,))
        ref = OLD_CHANGES[persona_id][0]
        line = "New core log for {} {} ({}):".format(
            ref['given_names'], ref['family_name'], persona_id)
        print(line, end="")
        if persona_id in ARCHIVED_PERSONAS:
            print(" archived")
            continue

        old_changes = OLD_CHANGES[persona_id]
        candidate_old = 1  # skip initial import
        newly_introduced = NEWLY_INTRODUCED_CHANGES[persona_id].copy()
        skipped = SKIPPED_CHANGES[persona_id].copy()
        for change in changes:
            if change['ctime'] > MIGRATION_TIME:
                break
            if newly_introduced and candidate_old == newly_introduced[0]:
                newly_introduced = newly_introduced[1:]
                print(f' [{change["id"]}->NEW]', end="")
                continue
            while skipped and candidate_old == skipped[0]:
                skipped = skipped[1:]
                candidate_old += 1
            old_change = old_changes[candidate_old]
            if compare_datum(change, old_change, additional_suppress={'change_note'}):
                print(f' [{change["id"]}->{old_change["ctime"]}]', end="")
                update = {'id': change['id'], 'ctime': old_change['ctime']}
                sql_update(cdb_conn, 'core.log', update)
                candidate_old += 1
            else:
                raise RuntimeError('Unmatched change!')
        if candidate_old == len(old_changes):
            print(" OK", end="")
        else:
            raise RuntimeError('Unconsumed changes!')
        print()

    # Update finance log
    for persona_id in persona_ids:
        query = "SELECT * FROM cde.finance_log WHERE persona_id = %s ORDER BY id"
        changes = query_all(cdb_conn, query, (persona_id,))
        old_changes = list(entry for entry in OLD_CHANGES[persona_id]
                           if entry['affects_finance'])
        ref = OLD_CHANGES[persona_id][0]
        line = "Finance log for {} {} ({}):".format(
            ref['given_names'], ref['family_name'], persona_id)
        print(line, end="")
        if persona_id in ARCHIVED_PERSONAS:
            print(" archived")
            continue

        candidate_old = 0
        candidate_lastschrift = 0
        skipped = SKIPPED_CHANGES[persona_id].copy()
        newly_introduced = NEWLY_INTRODUCED_CHANGES[persona_id].copy()
        for change in changes:
            if change['ctime'] > MIGRATION_TIME:
                break
            if change['code'] == 20:
                # Lastschrift
                lastschrift = LASTSCHRIFTS[persona_id][candidate_lastschrift]
                print(f' [{change["id"]}->{lastschrift["erteilt"]}]', end="")
                update = {'id': change['id'], 'ctime': lastschrift['erteilt']}
                sql_update(cdb_conn, 'cde.finance_log', update)
                candidate_lastschrift += 1
                continue
            old_change = old_changes[candidate_old]
            while (skipped and (OLD_CHANGES[persona_id].index(old_change) == skipped[0])):
                skipped = skipped[1:]
                candidate_old += 1
                old_change = old_changes[candidate_old]
            if (compare_datum(change, old_change, additional_suppress={'change_note'})
                    and change['code'] == old_change['finance_code']):
                print(f' [{change["id"]}->{old_change["ctime"]}]', end="")
                update = {'id': change['id'], 'ctime': old_change['ctime']}
                sql_update(cdb_conn, 'cde.finance_log', update)
                candidate_old += 1
            else:
                raise RuntimeError('Unmatched change!')
        if (candidate_old != len(old_changes)) and skipped:
            while (skipped and (OLD_CHANGES[persona_id].index(old_changes[candidate_old])
                                == skipped[0])):
                skipped = skipped[1:]
                candidate_old += 1
        if (candidate_old == len(old_changes)
                and candidate_lastschrift == len(LASTSCHRIFTS[persona_id])):
            print(" OK", end="")
        else:
            raise RuntimeError('Unconsumed changes!')
        print()

    if True:
        # Roll back
        raise RuntimeError("Dry run")
