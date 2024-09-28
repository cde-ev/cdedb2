#!/usr/bin/env python3
"""Generic script to recalculate the event fees for all users.

Should not be archived after use.
"""
import cProfile
import pathlib

import cdedb.fee_condition_parser.parsing as fcp_parse
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
        cProfile.run("event._update_registrations_amount_owed(rs, event_id)", str(pathlib.Path(__file__).parent / "../profiles/update_amounts_owed.prof"))
        print(fcp_parse.parse.cache_info())
