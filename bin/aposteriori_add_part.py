#!/usr/bin/env python3

import sys

from cdedb.script import Script

# Configuration

new_part = {
    'title': "Teil D",
    'shortname': "D",
    'part_begin': sys.argv[2],
    'part_end': sys.argv[3],
}

# Setup

script = Script(dbuser="cdb_admin")
event = script.make_backend("event")

update_event = {
    'parts': {
        -1: new_part,
    }
}

# Execution

with script:
    event.set_event(script.rs(), sys.argv[1], update_event)
