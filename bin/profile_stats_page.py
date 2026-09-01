#!/usr/bin/env python3
import cProfile
import sys

from cdedb.frontend.common import reconnoitre_ambience, setup_translations
from cdedb.script import Script

event_id = int(sys.argv[1])

# Prepare stuff
script = Script(dbuser="cdb_member")
user_rs = script.rs()

event = script.make_event_frontend(proxy=True)


class Mock:
    def __getattribute__(self, item):  # type: ignore[no-untyped-def]
        return {}


# Execution

with script:
    user_rs.requestargs = {'event_id': event_id}
    user_rs.request = Mock()  # type: ignore[assignment]
    user_rs.translations = setup_translations(script.config)
    user_rs.ambience = reconnoitre_ambience(event, user_rs)

    event.stats(user_rs, event_id)  # type: ignore[arg-type]
    cProfile.run("event.stats(user_rs, event_id)", sys.argv[2])
