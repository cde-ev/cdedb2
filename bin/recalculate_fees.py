#!/usr/bin/env python3
"""Generic script to recalculate the event fees for all users.

Should not be archived after use.
"""
from cdedb.backend.event import EventBackend
from cdedb.common.sorting import xsorted
from cdedb.script import Script

# setup

script = Script(persona_id=-1, dbuser="cdb_admin")
rs = script.rs()
event: EventBackend = script.make_backend("event", proxy=False)

# work

with script:
    for event_id, event_name in xsorted(event.list_events(rs).items()):
        print(f"Recalculating Fees for {event_name} with id {event_id}.")
        event._update_registrations_amount_owed(rs, event_id)  # pylint: disable=protected-access

