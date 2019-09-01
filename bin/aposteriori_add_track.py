#!/usr/bin/env python3

import sys
sys.path.insert(0, "/cdedb2/")
from cdedb.scripts import setup, make_backend

# Configuration

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

event_id = -1
part_id = -1
new_track = {
    'title': "Neue Kursschiene",
    'shortname': "Neu",
    'num_choices': 3,
    'sortkey': 1,
}

# Execution

event = make_backend("event")

update_event = {
    'id': event_id,
    'parts': {
        part_id: {
            'tracks': {
                -1: new_track,
            }
        }
    }
}
event.set_event(rs(), update_event)
