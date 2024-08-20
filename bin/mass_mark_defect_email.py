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
notes = "Massenimport defekter Emailadressen."  # explicate
email_addresses: list[str] = [
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
    for address in email_addresses:
        do_mark = True
        if address in lookup:
            diff = cutoff
            if lookup[address]['atime'] is not None:
                diff = now - lookup[address]['atime']
            if diff >= cutoff:
                print(f'Inactive account for `{address}` -- proceeding.')
            else:
                print(f'Active account for `{address}` -- skipping.')
        else:
            print(f'No account for `{address}` -- proceeding.')
        if do_mark:
            code = core.mark_email_status(rs, address, const.EmailStatus.defect,
                                          notes)
            if code:
                print(f'Marked as defect: `{address}`.')
            else:
                print(f'Failure for: `{address}`.')

