#!/usr/bin/env python3
"""Generic script to regenerate the fulltext field of a persona after changes.

Should not be archived after use.
"""
# setup

import time
from typing import Optional

from cdedb.common import PERSONA_ALL_FIELDS
from cdedb.script import make_backend, setup, Script, CoreBackend


# config

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")()

ALL_FIELDS = PERSONA_ALL_FIELDS + ("fulltext",)
core: CoreBackend = make_backend("core", proxy=False)
DRY_RUN = True
CHECK = True

# work

count = 0

with Script(rs, dry_run=DRY_RUN):
    persona_id = core.next_persona(rs, -1, is_member=None, is_archived=None)
    while persona_id is not None:
        persona = core.retrieve_persona(rs, persona_id, ALL_FIELDS)
        data = {
            'id': persona_id,
            'fulltext': core.create_fulltext(persona)
        }
        code = core.sql_update(rs, "core.personas", data)
        count += code
        if code != 1:
            raise RuntimeError(
                f"Somethings went wrong while updating persona {persona_id}.")
        else:
            print(persona_id, end=" ", flush=True)
        persona_id = core.next_persona(rs, persona_id, is_member=None, is_archived=None)
