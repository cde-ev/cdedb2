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
from typing import Collection

from psycopg2.extras import Json, RealDictCursor

from cdedb.common import CdEDBObject
from cdedb.config import (
    DEFAULT_CONFIGPATH, Config, TestConfig, get_configpath, set_configpath,
)
from cdedb.models.droid import OrgaToken
from cdedb.script import Script

# This is 'secret' the hashed
PHASH = ("$6$rounds=60000$uvCUTc5OULJF/kT5$CNYWFoGXgEwhrZ0nXmbw0jlWvqi/"
         "S6TDc1KJdzZzekFANha68XkgFFsw92Me8a2cVcK3TwSxsRPb91TLHF/si/")


# Add some default values for specific tables
def update_defaults(table: str, entry: CdEDBObject) -> CdEDBObject:
    if table != 'core.personas':
        return entry
    cde = entry['is_cde_realm']
    defaults = {
        'password_hash': PHASH,
        'is_event_realm': True,
        'is_searchable': False,
        'is_active': True,
        'balance': 0 if cde else None,
        'donation': 0 if cde else None,
        'trial_member': False if cde else None,
        'honorary_member': False if cde else None,
        'decided_search': True if cde else None,
        'bub_search': False if cde else None,
        'paper_expuls': True if cde else None,
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
        'foto': None,
        'fulltext': '',
        'notes': 'This is just a copy, changes to profiles will not be persisted.'
    }
    return {**defaults, **entry}


def populate_table(cur: RealDictCursor, table: str, data: CdEDBObject) -> None:
    """Insert the passed data into the DB."""
    if data:
        for entry in data.values():
            entry = update_defaults(table, entry)
            for k, v in entry.items():
                if isinstance(v, collections.abc.Mapping):
                    # No special care for serialization needed, since the data
                    # comes from a json load operation
                    entry[k] = Json(v)
            keys = tuple(key for key in entry)
            query = "INSERT INTO {table} ({keys}) VALUES ({placeholders})"
            query = query.format(table=table, keys=", ".join(keys),
                                 placeholders=", ".join(("%s",) * len(keys)))
            params = tuple(entry[key] for key in keys)
            cur.execute(query, params)
        # include a small buffer of 1000 (mainly to allow for the log
        # messages of locking the event if somebody gets the ordering wrong)
        query = "ALTER SEQUENCE {}_id_seq RESTART WITH {}".format(
            table, max(map(int, data)) + 1000)
        cur.execute(query)
    else:
        print("No data for table found")


def make_meta_info(cur: RealDictCursor) -> None:
    query = """INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb)"""
    cur.execute(query, tuple())


def shift_existing_ids(tables: list[str], shift_amount: int) -> None:
    connection = Script(dbuser="cdb", check_system_user=False).rs().conn
    with connection:
        with connection.cursor() as cur:
            query = """
                SELECT
                    conname,
                    nspname || '.' || relname AS tablename,
                    pg_catalog.pg_get_constraintdef(pg_constraint.oid, true) AS condef
                FROM
                    pg_catalog.pg_constraint
                    INNER JOIN pg_catalog.pg_class
                        ON pg_constraint.conrelid = pg_class.oid
                    INNER JOIN pg_catalog.pg_namespace
                        ON pg_class.relnamespace = pg_namespace.oid
                WHERE
                    contype = 'f' AND confupdtype != 'c'
                ORDER BY
                    relname
            """
            cur.execute(query, ())
            for x in list(cur.fetchall()):
                cur.execute(
                    f"ALTER TABLE {x['tablename']}"
                    f" DROP CONSTRAINT {x['conname']}",
                )
                cur.execute(
                    f"ALTER TABLE {x['tablename']}"
                    f" ADD CONSTRAINT {x['conname']} {x['condef']} ON UPDATE CASCADE",
                )
            for table in tables:
                query = f"""UPDATE {table} SET id = id + {shift_amount}"""
                cur.execute(query, ())


def update_event(cur: RealDictCursor, event: CdEDBObject) -> None:
    query = """UPDATE event.events SET lodge_field_id = %s"""
    cur.execute(query, [event['lodge_field_id']])


def update_parts(cur: RealDictCursor, parts: Collection[CdEDBObject]) -> None:
    query = """UPDATE event.event_parts
               SET (waitlist_field_id, camping_mat_field_id) = (%s, %s) WHERE id = %s"""
    for part in parts:
        params = (part['waitlist_field_id'], part['camping_mat_field_id'], part['id'])
        cur.execute(query, params)


def update_tracks(cur: RealDictCursor, tracks: Collection[CdEDBObject]) -> None:
    query = "UPDATE event.course_tracks SET course_room_field_id = %s WHERE id = %s"
    for track in tracks:
        cur.execute(query, (track['course_room_field_id'], track['id']))


def work(
        data_path: pathlib.Path, conf: Config, is_interactive: bool = True,
        extra_packages: bool = False, no_extra_packages: bool = False,
        dev_mode: bool = False, keep_data: bool = False, sample_data: bool = False,
        offline_mode: bool = True,
) -> None:
    repo_path: pathlib.Path = conf["REPOSITORY_PATH"]

    print("Loading exported event")
    with open(data_path, encoding='UTF-8') as infile:
        data = json.load(infile)

    if data.get("EVENT_SCHEMA_VERSION") != [17, 2]:
        raise RuntimeError("Version mismatch -- aborting.")
    if data["kind"] != "full":
        raise RuntimeError("Not a full export -- aborting.")
    print("Found data for event '{}' exported {}.".format(
        data['event.events'][str(data['id'])]['title'], data['timestamp']))

    if (
            not data['event.events'][str(data['id'])]['offline_lock']
            and (not dev_mode or offline_mode)
    ):
        print("Event not locked in online instance at time of export."
              "\nIn case of simultaneous changes in offline and online"
              " instance there will be data loss."
              "\nIf this is just a test run and you intend to scrap this"
              " offline instance you can ignore this warning.")
        if is_interactive:
            if (input("Continue anyway (type uppercase USE ANYWAY)? ").strip()
                    != "USE ANYWAY"):
                print("Aborting.")
                sys.exit()
        print("Fixing for offline use.")
        data['event.events'][str(data['id'])]['offline_lock'] = True

    if dev_mode and sample_data:
        print("Clean current instance (deleting all data)")
        if is_interactive:
            if input("Are you sure (type uppercase YES)? ").strip() != "YES":
                print("Aborting.")
                sys.exit()
        cmd = ['sudo', '-E', 'python3', '-m', 'cdedb', 'dev', 'apply-sample-data']
        if not args.test:
            cmd.append('--owner')
            cmd.append('www-cde')
            cmd.append('--group')
            cmd.append('www-data')
        subprocess.run(cmd, check=True)

    # connect to the database, using elevated access
    connection = Script(dbuser="cdb", check_system_user=False).rs().conn
    if dev_mode and (keep_data or sample_data):
        shift_existing_ids([k for k in data if '.' in k], 1_000_000)
    else:
        print("Clean current instance (deleting all data)")
        if is_interactive:
            if input("Are you sure (type uppercase YES)? ").strip() != "YES":
                print("Aborting.")
                sys.exit()
        clean_script = repo_path / "tests/ancillary_files/clean_data.sql"
        with connection as conn:
            with conn.cursor() as curr:
                curr.execute(clean_script.read_text())
        # Also clean out the event keeper storage
        for thing in (conf['STORAGE_DIR'] / 'event_keeper').iterdir():
            subprocess.run(["sudo", "rm", "-r", str(thing)], check=True)

    print("Setup the eventkeeper git repository.")
    cmd = ['sudo', '-E', 'python3', '-m', 'cdedb', 'filesystem', 'storage',
           'populate-event-keeper', str(data['id'])]
    if not args.test:
        cmd.insert(6, '--owner')
        cmd.insert(7, 'www-cde')
        cmd.insert(8, '--group')
        cmd.insert(9, 'www-data')
    subprocess.run(cmd, check=True)

    print("Make orgas into admins")
    orgas = {e['persona_id'] for e in data['event.orgas'].values()}
    for persona in data['core.personas'].values():
        if persona['id'] in orgas:
            bits = ["is_active", "is_core_admin", "is_cde_admin", "is_event_admin",
                    "is_cde_realm", "is_event_realm", "is_ml_realm", "is_assembly_realm"]
            for bit in bits:
                persona[bit] = True

    print("Remove inappropriate admin flags from all users")
    for persona in data['core.personas'].values():
        bits = ["is_meta_admin", "is_assembly_admin", "is_ml_admin"]
        for bit in bits:
            persona[bit] = False

    print("Prepare database.")
    # Fix uneditable table
    query = """GRANT SELECT, INSERT, UPDATE ON core.meta_info TO cdb_anonymous;
            GRANT SELECT, UPDATE ON core.meta_info_id_seq TO cdb_anonymous;
            INSERT INTO core.meta_info (info) VALUES ('{}'::jsonb);"""
    with connection as conn:
        with conn.cursor() as curr:
            curr.execute(query)

    # Order matters here:
    tables = (
        'core.personas', 'event.events', 'event.event_parts',
        'event.part_groups', 'event.part_group_parts',
        'event.courses', 'event.course_tracks', 'event.course_segments',
        'event.orgas', 'event.field_definitions', 'event.event_fees',
        'event.lodgement_groups', 'event.lodgements', 'event.registrations',
        'event.registration_parts', 'event.registration_tracks',
        'event.course_choices', 'event.questionnaire_rows', 'event.log',
        'event.stored_queries', 'event.track_groups', 'event.track_group_tracks',
        OrgaToken.database_table,
    )

    print("Connect to database")
    with connection as conn:
        with conn.cursor() as cur:
            make_meta_info(cur)
            for table in tables:
                print("Populating table {}".format(table))
                values = copy.deepcopy(data[table])
                # Prevent forward references
                if table == 'event.events':
                    for key in ('lodge_field_id',):
                        values[str(data['id'])][key] = None
                if table == 'event.event_parts':
                    for part_id in data[table]:
                        for key in ('waitlist_field_id', 'camping_mat_field_id'):
                            values[part_id][key] = None
                if table == 'event.course_tracks':
                    for track_id in data[table]:
                        for key in ('course_room_field_id',):
                            values[track_id][key] = None
                populate_table(cur, table, values)
            # Fix forward references
            update_event(cur, data['event.events'][str(data['id'])])
            update_parts(cur, data['event.event_parts'].values())
            update_tracks(cur, data['event.course_tracks'].values())

            # Create a surrogate changelog that can be used for the
            # duration of the offline deployment
            print("Instantiating changelog.")
            for persona in data['core.personas'].values():
                datum = update_defaults('core.personas', persona)
                del datum['id']
                del datum['password_hash']
                del datum['fulltext']
                datum['submitted_by'] = persona['id']
                datum['generation'] = 1
                datum['change_note'] = 'Create surrogate changelog.'
                datum['code'] = 2  # PersonaChangeStati.committed
                datum['persona_id'] = persona['id']
                keys = tuple(key for key in datum)
                query = (f"INSERT INTO core.changelog ({', '.join(keys)})"
                         f" VALUES ({', '.join(('%s',) * len(keys))})")
                params = tuple(datum[key] for key in keys)
                cur.execute(query, params)

    if not dev_mode or (not keep_data and not sample_data):
        print("Checking whether everything was transferred.")
        fails = []
        with conn as con:
            with con.cursor() as cur:
                for table in tables:
                    target_count = len(data[table])
                    query = "SELECT COUNT(*) AS count FROM {}".format(table)
                    cur.execute(query)
                    real_count = (cur.fetchone() or {'count': 0})['count']
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
        if dev_mode and not offline_mode:
            with conn as con:
                with con.cursor() as cur:
                    cur.execute("INSERT INTO cde.org_period (id) VALUES (42)")
                    cur.execute("INSERT INTO cde.expuls_period (id) VALUES (42)")

    # Adjust config.
    config_path = get_configpath()

    if not dev_mode:
        print("Enabling offline mode")
        # make sure to unset the development vm config option, so we do not clash
        subprocess.run(
            [
                "sudo", "sed", "-i", "-e", "s/CDEDB_DEV = True/CDEDB_DEV = False/",
                str(config_path),
            ],
            check=True,
        )

        print("Protecting data from accidental reset")
        subprocess.run(["sudo", "touch", "/OFFLINEVM"], check=True)

    if not dev_mode or offline_mode:
        # mark the config as offline vm
        offline_deploy_key = "CDEDB_OFFLINE_DEPLOYMENT"
        if not Config()[offline_deploy_key]:
            # Try replacing config entry.
            subprocess.run(
                [
                    "sudo", "sed", "-i", "-e",
                    f"s/{offline_deploy_key} = False/{offline_deploy_key} = True/",
                    str(config_path),
                ], check=True,
            )
            # If that didn't work, add a new one.
            if not Config()[offline_deploy_key]:
                with open(str(config_path), 'a', encoding='UTF-8') as conf_file:
                    conf_file.write(f"\n{offline_deploy_key} = True\n")

    if no_extra_packages:
        print("Skipping installation of fonts for template renderer.")
        install_fonts = False
    elif extra_packages:
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
    subprocess.run(["make", "reload"], check=True, cwd=repo_path)

    print("Finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Prepare for offline usage.')
    parser.add_argument('data_path', help="Path to exported event data")
    parser.add_argument('-t', '--test', action="store_true",
                        help="Operate on test database")
    parser.add_argument('--not-interactive', action="store_true",
                        help="Supress confirmation prompt before irreversible changes.")
    parser.add_argument('-e', '--extra-packages', action="store_true",
                        help="Unconditionally install additional packages.")
    parser.add_argument('-E', '--no-extra-packages', action="store_true",
                        help="Never install additional packages.")
    parser.add_argument('--dev', action="store_true",
                        help="Setup offline VM for development/manual testing.")
    parser.add_argument('--no-offline-flag', action="store_true",
                        help="Do not set the config flag for offline mode."
                             " Only available with '--dev'.")
    parser.add_argument('--keep-data', action="store_true",
                        help="Do not remove existing data. May cause this to fail."
                             " Only available with '--dev'.")
    parser.add_argument('--sample-data', action="store_true",
                        help="Also populate with sample data."
                             " Could conceivably cause this to fail."
                             " Only available with '--dev'.")
    args = parser.parse_args()
    if args.extra_packages and args.no_extra_packages:
        parser.error("Confliction options for (no) additional packages.")

    data_path = pathlib.Path(args.data_path)

    config: Config
    if args.test:
        # the configpath is already set and intended to be used here
        config = TestConfig()
    else:
        # otherwise, we want to use the default configpath of the real world
        set_configpath(DEFAULT_CONFIGPATH)
        config = Config()

    work(
        data_path, config, is_interactive=not args.not_interactive,
        extra_packages=args.extra_packages, no_extra_packages=args.no_extra_packages,
        dev_mode=args.dev, keep_data=args.keep_data, sample_data=args.sample_data,
        offline_mode=not args.no_offline_flag,
    )
