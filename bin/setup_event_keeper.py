#!/usr/bin/env python3
"""Deployment script for event keeper, doing core setup of the new facility.

Since this is storage-only, dry run is meaningless here.
After deployment, also run setup_event_keeper.sh to allow git access from outside.
"""
from pathlib import Path

from cdedb.backend.event import EventBackend
from cdedb.script import Script

# Prepare stuff

script = Script(dbuser="cdb_persona", persona_id=0, dry_run=False)
rs = script.rs()
event: EventBackend = script.make_backend("event")

# Execution

with script:
    events = event.list_events(rs)

    # Create root directory for event keeper
    root_dir: Path = script.config["STORAGE_DIR"] / "event_keeper"
    root_dir.mkdir()

    for event_id in events:
        event.event_keeper_create(rs, event_id)
