#!/usr/bin/env python3
"""Mark a large amount of email addresses as defect."""

import datetime

import cdedb.database.constants as const
from cdedb.backend.common import Silencer
from cdedb.script import Script

# setup

script = Script(persona_id=-1, dbuser="cdb_admin", dry_run=True)
rs = script.rs()
core = script.make_backend("core", proxy=False)
cutoff = datetime.timedelta(days=90)
target_state = const.EmailStatus.defect
default_notes = "Massenimport defekter Emailadressen."  # explicate
email_addresses: list[tuple[str, str]] = [
    # fill in
]

# work

now = datetime.datetime.now(datetime.timezone.utc)
with script:
    query = (
        "SELECT p.id, p.username, p.given_names, p.family_name, MAX(s.atime) AS atime"
        " FROM core.personas AS p LEFT OUTER JOIN core.sessions AS s"
        " ON s.persona_id = p.id WHERE username = ANY(%s) GROUP BY (p.id)")
    params = (email_addresses,)
    data = core.query_all(rs, query, params)
    lookup = {entry['username']: entry for entry in data}

    query = "SELECT address, status, notes FROM core.email_states"
    data = core.query_all(rs, query, tuple())
    preexisting = {entry['address']: entry for entry in data}

    for address, notes in email_addresses:
        if address.lower() in preexisting:
            preex = preexisting[address]
            if preex['status'] == target_state:
                print(f'Not touching existing entry for `{address}`'
                      f' (old notes: ```{preex["notes"]}```;'
                      f' new notes: ```{notes}```).')
            else:
                print(f'Not transitioning existing entry for `{address}`'
                      f' (old notes: ```{preex["notes"]}```;'
                      f' new notes: ```{notes}```).')
            continue
        do_mark = True
        notes = notes or default_notes
        if address in lookup:
            diff = cutoff
            if lookup[address]['atime'] is not None:
                diff = now - lookup[address]['atime']
            if diff >= cutoff:
                print(f'Inactive account for `{address}` -- proceeding.')
            else:
                print(f'Active account for `{address}` -- skipping.')
                do_mark = False
        else:
            print(f'No account for `{address}` -- proceeding.')
        if do_mark:
            code = core.mark_email_status(rs, address, target_state, notes)
            if code:
                print(f'Marked as defect: `{address}`.')
            else:
                print(f'Failure for: `{address}`.')

