#! /usr/bin/env python3
"""
Perfectly balanced, as all things should be.

Run as:
  `sudo -u www-cde SCRIPT_PERSONA=X bin/balance_event.py`.

Turn off dry run with:
  `sudo -u www-cde SCRIPT_PERSONA=X SCRIPT_DRYRUN="" bin/balance_event.py`.`
"""

from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.script import Script

MAX_EVENT_ID = 66

s = Script(dbuser="cdb_member")
event_backend = s.make_event_backend(proxy=True)
core_backend = s.make_core_backend(proxy=True)

rs = s.rs()

# This is necessary because balancing creates an event keeper commit,
#  which requires user information, else git is very unhappy :(
persona = core_backend.get_persona(rs, rs.user.persona_id)
rs.user.username = persona.username
rs.user.given_names = persona.given_names
rs.user.family_name = persona.family_name

balance_count = 0
non_archived_count = 0

with s:
    event_ids = event_backend.list_events(rs)
    events = event_backend.get_events(rs, event_ids)
    for event in events.values():
        if event.is_balanced:
            print(f"{event.title} is already balanced. Skipping…")
            continue
        if event.id > MAX_EVENT_ID:
            print(f"{event.title} is too recent. Skipping…")
            continue
        if not event.is_archived:
            print(f"{event.title} is not yet archived! Balancing it anyway.")
            non_archived_count += 1
        event_backend.balance_event(rs, event.id)
        print(f"{event.title} is now perfectly balanced, as all things should be.")
        balance_count += 1

    print("\n" + "–" * 80 + "\n")
    print(f"Balanced {balance_count} events.")
    if non_archived_count:
        print(f"{non_archived_count} of which are not yet archived.")
