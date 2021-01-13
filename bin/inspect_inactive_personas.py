#!/usr/bin/env python3
import datetime
from typing import NamedTuple, Set

from cdedb.common import now
from cdedb.script import make_backend, setup, Script

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = -1
rs = setup(persona_id=executing_admin_id, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

DRY_RUN = True
CUTOFF = datetime.timedelta(days=365)

# Prepare stuff

core = make_backend("core")

Counter = NamedTuple("Counter", (("ids", Set[int]), ("members", Set[int])))

# Execution

with Script(rs(), dry_run=DRY_RUN):
    no_session = Counter(set(), set())
    old_session = Counter(set(), set())
    recent_session = Counter(set(), set())
    timestamp = now()
    persona_id = -1
    while True:
        persona_id = core.next_persona(rs(), persona_id, is_member=False)
        if persona_id is None:
            break

        latest_session = core.get_persona_latest_session(rs(), persona_id)
        diff = timestamp - latest_session if latest_session else None
        # print(f"{persona_id}: {latest_session} {diff}")

        persona = core.get_persona(rs(), persona_id)
        if diff is None:
            pointer = no_session
        elif diff > CUTOFF:
            pointer = old_session
        else:
            pointer = recent_session
        pointer.ids.add(persona_id)
        if persona["is_member"]:
            pointer.members.add(persona_id)

    print(f"{len(no_session.ids)} users have no sessions on record,"
          f" {len(no_session.members)} of which are currently members.")
    print(f"{len(old_session.ids)} users have no recent sessions on record,"
          f" {len(old_session.members)} of which are currently members.")
    print(f"{len(recent_session.ids)} users have recent sessions on record,"
          f" {len(recent_session.members)} of which are currently members.")

