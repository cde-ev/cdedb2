#!/usr/bin/env python3
import cProfile
import sys

from cdedb.frontend.common import reconnoitre_ambience, setup_translations
from cdedb.frontend.event import EventFrontend
from cdedb.script import Script

# Configuration

# The admin id will need to be replaces before use.
executing_admin_id = int(sys.argv[1])
event_id = int(sys.argv[2])

# Prepare stuff
script = Script(persona_id=executing_admin_id, dbuser="cdb_admin")
user_rs = script.rs()

event: EventFrontend = script.make_frontend(realm="event")


class Mock:
    def __getattribute__(self, item):  # type: ignore[no-untyped-def]
        return {}


# Execution

with script:
    user_rs.requestargs = {'event_id': event_id}
    user_rs.request = Mock()  # type: ignore[assignment]
    user_rs.translations = setup_translations(script.config)
    user_rs.ambience = reconnoitre_ambience(event, user_rs)

    cProfile.run("event.stats(user_rs, event_id)", sys.argv[3])
