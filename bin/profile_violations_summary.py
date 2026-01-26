#!/usr/bin/env python3
import cProfile
import sys

from cdedb.frontend.common import reconnoitre_ambience, setup_translations
from cdedb.script import Script

# Prepare stuff
script = Script(dbuser="cdb_member")
user_rs = script.rs()

event = script.make_event_frontend(proxy=True)


class Mock:
    def __getattribute__(self, item):  # type: ignore[no-untyped-def]
        return {}


# Execution

with script:
    user_rs.request = Mock()  # type: ignore[assignment]
    user_rs.translations = setup_translations(script.config)
    user_rs.ambience = reconnoitre_ambience(event, user_rs)

    event.constraint_violations_summary(user_rs)

    cProfile.run("event.constraint_violations_summary(user_rs)", sys.argv[1])
