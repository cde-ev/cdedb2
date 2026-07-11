#!/usr/bin/env -S uv run
import pathlib

from cdedb.script import Script
from cdedb.common import json_serialize

s = Script(dbuser="cdb_persona", check_system_user=False)

event = s.make_event_backend()

partial_export_path = pathlib.Path(__file__).parent.parent / "tests" / "ancillary_files" / "TestAka_partial_export_event.json"
full_export_path = pathlib.Path(__file__).parent.parent / "tests" / "ancillary_files" / "event_export.json"

partial_export_path.write_text(json_serialize(event.partial_export_event(s.rs(), event_id=1), sort_keys=True))
full_export_path.write_text(json_serialize(event.export_event(s.rs(), event_id=1), sort_keys=True))
