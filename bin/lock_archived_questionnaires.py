#!/usr/bin/env python3
"""Explicitly lock all questionnaire fields for all currently archived events."""
import cdedb.database.constants as const
from cdedb.backend.common import Silencer
from cdedb.script import Script

# setup

script = Script(persona_id=-1, dbuser="cdb_admin")
rs = script.rs()
event = script.make_backend("event")

# work

with script:
    with Silencer(rs):
        event_ids = event.list_events(rs, archived=True)
        for event_id in event_ids:
            aq = const.QuestionnaireUsages.additional
            questionnaire = event.get_questionnaire(rs, event_id, [aq])[aq]
            for entry in questionnaire:
                entry['readonly'] = True
            event.set_questionnaire(rs, event_id, {aq: questionnaire})
