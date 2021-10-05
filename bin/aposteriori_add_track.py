#!/usr/bin/env python3

from cdedb.script import Script

# Configuration

admin_id = -1
event_id = 1
part_id = 1
new_track = {
    'title': "Neue Kursschiene",
    'shortname': "Neu",
    'min_choices': 3,
    'num_choices': 3,
    'sortkey': 1,
}

# Setup

script = Script(persona_id=admin_id, dbuser="cdb_admin")
event = script.make_backend("event")

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

event.set_event(script.rs(), update_event)
