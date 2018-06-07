#!/usr/bin/env python3

"""Script for importing an event into the VM and preparing for offline usage.

This destroys all data in the current instance and replaces it with the
provided exported event. The VM is then put into offline mode.
"""

import argparse
import collections
import json
import pathlib
import subprocess
import sys

import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

#: Add some default values for specific tables
defaults = {
    'core.personas': {
        'password_hash': '$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/',
        'is_event_realm': True,
        'is_searchable': False,
        'is_active': True,
        'cloud_account': False,
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
    for entry in data:
        if table in defaults:
            entry.update(defaults[table])
        for k, v in entry.items():
            if isinstance(v, collections.Mapping):
                ## No special care for serialization needed, since the data
                ## comes from a json load operation
                entry[k] = psycopg2.extras.Json(v)
        keys = tuple(key for key in entry)
        query = "INSERT INTO {table} ({keys}) VALUES ({placeholders})"
        query = query.format(table=table, keys=", ".join(keys),
                             placeholders=", ".join(("%s",) * len(keys)))
        params = tuple(entry[key] for key in keys)
        cur.execute(query, params)

if __name__ == "__main__":
    ## analyze command line arguments
    parser = argparse.ArgumentParser(
        description='Prepare for offline usage.')
    parser.add_argument('data_path', help="Path to exported event data")
    args = parser.parse_args()

    ## detemine repo path
    currentpath = pathlib.Path(__file__).resolve().parent
    if (currentpath.parts[0] != '/'
            or currentpath.parts[-1] != 'bin'):
        raise RuntimeError("Failed to locate repository")
    repopath = currentpath.parent

    ## do the actual work

    print("Loading exported event")
    with open(args.data_path, encoding='UTF-8') as infile:
        data = json.load(infile)

    if data["CDEDB_EXPORT_EVENT_VERSION"] != 1:
        raise RuntimeError("Version mismatch -- aborting.")
    print("Found data for event '{}' exported {}.".format(
        data['event.events'][0]['title'], data['timestamp']))

    print("Clean current instance")
    if input("Are you sure (type uppercase YES)? ").strip() != "YES":
        print("Aborting.")
        sys.exit()
    clean_script = repopath / "test/ancillary_files/clean_data.sql"
    subprocess.check_call(
        ["sudo", "-u", "cdb", "psql", "-U", "cdb", "-d", "cdb", "-f",
         str(clean_script)], stderr=subprocess.DEVNULL)

    print("Connect to database")
    connection_string = "dbname={} user={} password={} port={}".format(
        'cdb', 'cdb', '987654321098765432109876543210', 5432)
    conn = psycopg2.connect(connection_string,
                            cursor_factory=psycopg2.extras.RealDictCursor)
    conn.set_client_encoding("UTF8")

    with conn as con:
        with con.cursor() as cur:
            for table in ('core.personas', 'event.events', 'event.event_parts',
                          'event.courses', 'event.course_parts', 'event.orgas',
                          'event.field_definitions', 'event.lodgements',
                          'event.registrations', 'event.registration_parts',
                          'event.course_choices', 'event.questionnaire_rows'):
                print("Populating table {}".format(table))
                populate_table(cur, table, data[table])

    print("Enabling offline mode")
    config_path = repopath / "cdedb/localconfig.py"
    subprocess.check_call(
        ["sed", "-i", "-e", "s/CDEDB_DEV = True/CDEDB_DEV = False/",
         str(config_path)])
    with open(str(config_path), 'a', encoding='UTF-8') as conf:
        conf.write("\nCDEDB_OFFLINE_DEPLOYMENT = True\n")

    print("Finished")
