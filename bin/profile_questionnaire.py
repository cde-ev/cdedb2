#!/usr/bin/env python3
import cProfile
import sys

from cdedb.frontend.common import reconnoitre_ambience, setup_translations
from cdedb.script import Script

event_id = int(sys.argv[1])
persona_id = int(sys.argv[2])

# Prepare stuff
script = Script(dbuser="cdb_member", persona_id=persona_id)
user_rs = script.rs()

event_frontend = script.make_event_frontend(proxy=False)
event_backend = script.make_event_backend(proxy=False)


class Mock:
    def __getattribute__(self, item):  # type: ignore[no-untyped-def]
        return {}


# Execution

with script:
    user_rs.requestargs = {'event_id': event_id}
    user_rs.request = Mock()  # type: ignore[assignment]
    user_rs.translations = setup_translations(script.config)
    user_rs.ambience = reconnoitre_ambience(event_frontend, user_rs)

    event = event_backend.get_event(user_rs, event_id)
    if not event.use_additional_questionnaire:
        if script.config["CDEDB_DEV"]:
            event_backend.set_event(
                user_rs, event_id, {"use_additional_questionnaire": True}
            )
        else:
            print(f"Questionnaire not available for {event.shortname}.")
            sys.exit(1)

    def run() -> None:
        event_frontend.additional_questionnaire_form(user_rs, event_id)

    run()
    cProfile.run("run()", sys.argv[-1])
