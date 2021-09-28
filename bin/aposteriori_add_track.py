#!/usr/bin/env python3

from cdedb.script import Script

# Configuration

event_id = -1
part_id = -1
new_track = {
    'title': "Neue Kursschiene",
    'shortname': "Neu",
    'min_choices': 3,
    'num_choices': 3,
    'sortkey': 1,
}

# Setup

s = Script(persona_id=-1, dbuser="cdb_admin")
event = s.make_backend("event")

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

# Execution

event.set_event(s.rs(), update_event)
