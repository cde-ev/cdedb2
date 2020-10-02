#!/usr/bin/env python3

"""Script for importing an event into the VM and preparing for offline usage.

This destroys all data in the current instance and replaces it with the
provided exported event. The VM is then put into offline mode.
"""

import argparse
import collections.abc
import copy
import json
import pathlib
import subprocess
import sys

import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

# This is 'secret' the hashed
PHASH = ("$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
         "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/")

# Add some default values for specific tables
DEFAULTS = {
    'core.personas': {
        'password_hash': PHASH,
        'is_event_realm': True,
        'is_searchable': False,
        'is_active': True,
        'balance': 0,
        'birth_name': None,
        'address_supplement2': None,
        'address2': None,
        'postal_code2': None,
        'location2': None,
        'country2': None,
        'weblink': None,
        'specialisation': None,
        'affiliation': None,
        'timeline': None,
        'interests': None,
        'free_form': None,
        'trial_member': False,
        'decided_search': False,
        'bub_search': False,
        'foto': None,
        'fulltext': '',
    }
}


def populate_table(cur, table, data):
    """Insert the passed data into the DB.

    :type cur: psycopg cursor
    :type table: str
    :type data: {str: object}
    """
    if data:
        for entry in data.values():
            if table in DEFAULTS:
                entry = {**DEFAULTS[table], **entry}
            for k, v in entry.items():
                if isinstance(v, collections.abc.Mapping):
                    # No special care for serialization needed, since the data
                    # comes from a json load operation
                    entry[k] = psycopg2.extras.Json(v)
            keys = tuple(key for key in entry)
            query = "INSERT INTO {table} ({keys}) VALUES ({placeholders})"
            query = query.format(table=table, keys=", ".join(keys),
                                 placeholders=", ".join(("%s",) * len(keys)))
            params = tuple(entry[key] for key in keys)
            cur.execute(query, params)
        # include a small buffer of 1000 (mainly to allow for the log
        # messages of locking the event if somebody gets the ordering wrong)
        query = "ALTER SEQUENCE {}_id_seq RESTART WITH {}".format(
            table, max(int(id) for id in data) + 1000)
        # we need elevated privileges for sequences
        subprocess.run(
            ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", "cdb", "-c",
             query], stderr=subprocess.DEVNULL, check=True)
    else:
        print("No data for table found")


def make_institution(cur, institution_id):
    query = """INSERT INTO past_event.institutions (id, title, shortname)
               VALUES (%s, %s, %s)"""
    params = (institution_id, 'Veranstaltungsservice', 'CdE')
    cur.execute(query, params)


def make_meta_info(cur):
    query = """INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb)"""
    params = tuple()
    cur.execute(query, params)


def update_event(cur, event):
    query = """UPDATE event.events
               SET (lodge_field, camping_mat_field, course_room_field)
               = (%s, %s, %s)"""
    params = (event['lodge_field'], event['camping_mat_field'],
              event['course_room_field'])
    cur.execute(query, params)


def work(args):
    db_name = 'cdb_test' if args.test else 'cdb'

    print("Loading exported event")
    with open(args.data_path, encoding='UTF-8') as infile:
        data = json.load(infile)

    if data.get("EVENT_SCHEMA_VERSION") != [14, 1]:
        raise RuntimeError("Version mismatch -- aborting.")
    if data["kind"] != "full":
        raise RuntimeError("Not a full export -- aborting.")
    print("Found data for event '{}' exported {}.".format(
        data['event.events'][str(data['id'])]['title'], data['timestamp']))

    if not data['event.events'][str(data['id'])]['offline_lock']:
        print("Event not locked in online instance at time of export."
              "\nIn case of simultaneous changes in offline and online"
              " instance there will be data loss."
              "\nIf this is just a test run and you intend to scrap this"
              " offline instance you can ignore this warning.")
        if not args.test:
            if (input("Continue anyway (type uppercase USE ANYWAY)? ").strip()
                    != "USE ANYWAY"):
                print("Aborting.")
                sys.exit()
        print("Fixing for offline use.")
        data['event.events'][str(data['id'])]['offline_lock'] = True

    print("Clean current instance (deleting all data)")
    if not args.test:
        if input("Are you sure (type uppercase YES)? ").strip() != "YES":
            print("Aborting.")
            sys.exit()
    clean_script = args.repopath / "test/ancillary_files/clean_data.sql"
    subprocess.run(
        ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", db_name, "-f",
         str(clean_script)], stderr=subprocess.DEVNULL, check=True)

    print("Make orgas into admins")
    orgas = {e['persona_id'] for e in data['event.orgas'].values()}
    for persona in data['core.personas'].values():
        if persona['id'] in orgas:
            bits = (
                "is_active", "is_core_admin", "is_cde_admin", "is_event_admin",
                "is_cde_realm", "is_event_realm", "is_ml_realm")
            for bit in bits:
                persona[bit] = True

    print("Remove inappropriate admin flags from all users")
    for persona in data['core.personas'].values():
        bits = ("is_meta_admin", "is_assembly_admin", "is_ml_admin")
        for bit in bits:
            persona[bit] = False

    print("Prepare database.")
    # Fix uneditable table
    subprocess.run(
        ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", db_name, "-c",
         """GRANT SELECT, INSERT, UPDATE ON core.meta_info TO cdb_anonymous;
            GRANT SELECT, UPDATE ON core.meta_info_id_seq TO cdb_anonymous;
            INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb);"""],
        stderr=subprocess.DEVNULL, check=True)

    print("Connect to database")
    connection_string = "dbname={} user={} password={} port={}".format(
        db_name, 'cdb_admin', '9876543210abcdefghijklmnopqrst', 5432)
    conn = psycopg2.connect(connection_string,
                            cursor_factory=psycopg2.extras.RealDictCursor)
    conn.set_client_encoding("UTF8")

    tables = (
        'core.personas', 'event.events', 'event.event_parts',
        'event.courses', 'event.course_tracks', 'event.course_segments',
        'event.orgas', 'event.field_definitions', 'event.lodgement_groups',
        'event.lodgements', 'event.registrations',
        'event.registration_parts', 'event.registration_tracks',
        'event.course_choices', 'event.questionnaire_rows', 'event.log')
    with conn as con:
        with con.cursor() as cur:
            make_institution(
                cur, data['event.events'][str(data['id'])]['institution'])
            make_meta_info(cur)
            for table in tables:
                print("Populating table {}".format(table))
                values = copy.deepcopy(data[table])
                # Prevent forward references
                if table == 'event.events':
                    for key in ('lodge_field', 'camping_mat_field',
                                'course_room_field'):
                        values[str(data['id'])][key] = None
                populate_table(cur, table, values)
            # Fix forward references
            update_event(cur, data['event.events'][str(data['id'])])

            # Create a surrogate changelog that can be used for the
            # duration of the offline deployment
            print("Instantiating changelog.")
            for persona in data['core.personas'].values():
                datum = {**DEFAULTS['core.personas'], **persona}
                del datum['id']
                del datum['password_hash']
                del datum['fulltext']
                datum['notes'] = ('This is just a copy, changes to profiles'
                                  ' will not be persisted.')
                datum['submitted_by'] = persona['id']
                datum['generation'] = 1
                datum['change_note'] = 'Create surrogate changelog.'
                datum['code'] = 2  # MemberChangeStati.committed
                datum['persona_id'] = persona['id']
                keys = tuple(key for key in datum)
                query = ("INSERT INTO core.changelog ({keys})"
                         " VALUES ({placeholders})").format(
                             table=table, keys=", ".join(keys),
                             placeholders=", ".join(("%s",) * len(keys)))
                params = tuple(datum[key] for key in keys)
                cur.execute(query, params)

    print("Checking whether everything was transferred.")
    fails = []
    with conn as con:
        with con.cursor() as cur:
            for table in tables:
                target_count = len(data[table])
                query = "SELECT COUNT(*) AS count FROM {}".format(table)
                cur.execute(query)
                real_count = cur.fetchone()['count']
                if target_count != real_count:
                    fails.append("Table {} has {} not {} entries".format(
                        table, real_count, target_count))
    if fails:
        print("Errors detected.")
        for fail in fails:
            print(fail)
        raise RuntimeError("Data transfer was not successful.")
    else:
        print("Everything in place.")

    print("Enabling offline mode")
    config_path = args.repopath / "cdedb/localconfig.py"
    subprocess.run(
        ["sed", "-i", "-e", "s/CDEDB_DEV = True/CDEDB_DEV = False/",
         str(config_path)], check=True)
    with open(str(config_path), 'a', encoding='UTF-8') as conf:
        conf.write("\nCDEDB_OFFLINE_DEPLOYMENT = True\n")

    print("Protecting data from accidental reset")
    subprocess.run(["sudo", "touch", "/OFFLINEVM"], check=True)

    install_fonts = None
    if args.no_extra_packages:
        print("Skipping installation of fonts for template renderer.")
        install_fonts = False
    elif args.extra_packages:
        print("Unconditionally installing fonts for template renderer.")
        install_fonts = True
    else:
        print("Installation of fonts for template renderer.")
        print("If you confirm this will download 500MB of data.")
        print("You can also do this later with"
              " 'sudo apt-get install texlive-fonts-extra'.")
        print("Without this the template renderer will obviously not work.")
        decision = input("Do you want to install the fonts (y/n)?")
        install_fonts = decision.strip().lower() in {'y', 'yes', 'j', 'ja'}
    if install_fonts:
        subprocess.run(
            ["sudo", "apt-get", "-y", "install", "texlive-fonts-extra"],
            check=True)

    print("Restarting application to make offline mode effective")
    subprocess.run(["make", "reload"], check=True, cwd=args.repopath)

    print("Finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Prepare for offline usage.')
    parser.add_argument('data_path', help="Path to exported event data")
    parser.add_argument('-t', '--test', action="store_true",
                        help="Operate on test database")
    parser.add_argument('-e', '--extra-packages', action="store_true",
                        help="Unconditionally install additional packages.")
    parser.add_argument('-E', '--no-extra-packages', action="store_true",
                        help="Never install additional packages.")
    args = parser.parse_args()
    if args.extra_packages and args.no_extra_packages:
        parser.error("Confliction options for (no) additional packages.")

    # detemine repo path
    currentpath = pathlib.Path(__file__).resolve().parent
    if (currentpath.parts[0] != '/'
            or currentpath.parts[-1] != 'bin'):
        raise RuntimeError("Failed to locate repository")
    args.repopath = currentpath.parent

    work(args)
