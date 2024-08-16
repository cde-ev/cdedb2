#!/usr/bin/env python3
"""Deployment script for the new attachment storage,

Since this is storage-only, dry run is meaningless here.
After deployment, also run setup_event_keeper.sh to allow git access from outside.
"""
import os
import shutil
from pathlib import Path

from cdedb.common import get_hash
from cdedb.script import Script

# Prepare stuff

script = Script(dbuser="cdb_persona", persona_id=0, dry_run=False)

# Execution

with script:
    # Create root directory for event keeper
    root_dir: Path = script.config["STORAGE_DIR"] / "assembly_attachment"
    count = 0

    with os.scandir(root_dir) as it:
        for entry in it:
            if entry.is_file():
                with open(entry.path, "rb") as f:
                    file_hash = get_hash(f.read())
                shutil.move(entry.path, root_dir / file_hash)
                print(f"{entry.name} moved to {root_dir / file_hash}.")
                count += 1

    print(f"Moved {count} files in {root_dir}.")
