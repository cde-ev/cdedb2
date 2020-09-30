#!/usr/bin/env python3

from cdedb.script import setup, make_backend

# Configuration

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")

event_id = -1
part_id = -1
new_track = {
    'title': "Neue Kursschiene",
    'shortname': "Neu",
    'min_choices': 3,
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
