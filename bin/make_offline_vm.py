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


def make_institution(cur, institution_id):
    query = """INSERT INTO past_event.institutions (id, title, moniker)
               VALUES (%s, %s, %s)"""
    params = (institution_id, 'Veranstaltungsservice', 'CdE')
    cur.execute(query, params)


def make_meta_info(cur):
    query = """INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb)"""
    params = tuple()
    cur.execute(query, params)


def update_event(cur, event):
    query = """UPDATE event.events
               SET (lodge_field, reserve_field, course_room_field)
               = (%s, %s, %s)"""
    params = (event['lodge_field'], event['reserve_field'],
              event['course_room_field'])
    cur.execute(query, params)


def work(args):
    print("Loading exported event")
    with open(args.data_path, encoding='UTF-8') as infile:
        data = json.load(infile)

    if data["CDEDB_EXPORT_EVENT_VERSION"] != 1:
        raise RuntimeError("Version mismatch -- aborting.")
    if data["kind"] != "full":
        raise RuntimeError("Not a full export -- aborting.")
    print("Found data for event '{}' exported {}.".format(
        data['event.events'][str(data['id'])]['title'], data['timestamp']))

    if not data['event.events'][str(data['id'])]['offline_lock']:
        print("Event not locked in online instance. Fixing for offline use.")
        data['event.events'][str(data['id'])]['offline_lock'] = True

    print("Clean current instance")
    if input("Are you sure (type uppercase YES)? ").strip() != "YES":
        print("Aborting.")
        sys.exit()
    clean_script = args.repopath / "test/ancillary_files/clean_data.sql"
    subprocess.check_call(
        ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", "cdb", "-f",
         str(clean_script)], stderr=subprocess.DEVNULL)

    # Fix uneditable table
    subprocess.check_call(
        ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", "cdb", "-c",
         """GRANT SELECT, INSERT, UPDATE ON core.meta_info TO cdb_anonymous;
            GRANT SELECT, UPDATE ON core.meta_info_id_seq TO cdb_anonymous;
            INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb);"""],
        stderr=subprocess.DEVNULL)

    print("Connect to database")
    connection_string = "dbname={} user={} password={} port={}".format(
        'cdb', 'cdb_admin', '9876543210abcdefghijklmnopqrst', 5432)
    conn = psycopg2.connect(connection_string,
                            cursor_factory=psycopg2.extras.RealDictCursor)
    conn.set_client_encoding("UTF8")

    tables = (
        'core.personas', 'event.events', 'event.event_parts',
        'event.courses', 'event.course_tracks', 'event.course_segments',
        'event.orgas', 'event.field_definitions', 'event.lodgements',
        'event.registrations', 'event.registration_parts',
        'event.registration_tracks',
        'event.course_choices', 'event.questionnaire_rows')
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
                    for key in ('lodge_field', 'reserve_field',
                                'course_room_field'):
                        values[str(data['id'])][key] = None
                populate_table(cur, table, values)
            # Fix forward references
            update_event(cur, data['event.events'][str(data['id'])])

    print("Enabling offline mode")
    config_path = args.repopath / "cdedb/localconfig.py"
    subprocess.check_call(
        ["sed", "-i", "-e", "s/CDEDB_DEV = True/CDEDB_DEV = False/",
         str(config_path)])
    with open(str(config_path), 'a', encoding='UTF-8') as conf:
        conf.write("\nCDEDB_OFFLINE_DEPLOYMENT = True\n")

    print("Finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Prepare for offline usage.')
    parser.add_argument('data_path', help="Path to exported event data")
    args = parser.parse_args()

    # detemine repo path
    currentpath = pathlib.Path(__file__).resolve().parent
    if (currentpath.parts[0] != '/'
            or currentpath.parts[-1] != 'bin'):
        raise RuntimeError("Failed to locate repository")
    args.repopath = currentpath.parent

    work(args)
