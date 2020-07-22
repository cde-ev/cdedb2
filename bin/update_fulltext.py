#!/usr/bin/env python3
# setup

import sys
import time

sys.path.insert(0, "/cdedb2/")
from cdedb.script import make_backend, setup
from cdedb.database.connection import Atomizer
from cdedb.common import PERSONA_ALL_FIELDS

# config

rs = setup(persona_id=-1, dbuser="cdb_admin",
           dbpassword="9876543210abcdefghijklmnopqrst")()

ALL_FIELDS = PERSONA_ALL_FIELDS + ("fulltext",)
core = make_backend("core", proxy=False)
DRY_RUN = True
CHECK = True

# work

persona_id = 0
count = 0
start = time.time()
with Atomizer(rs):
    persona_id = core.next_persona(rs, persona_id, is_member=False)
    while persona_id is not None:
        persona = core.retrieve_persona(rs, persona_id, ALL_FIELDS)
        if CHECK:
            if not str(persona_id) == persona["fulltext"].split(" ", 1)[0]:
                raise AssertionError(f"Persona {persona_id} does not have"
                                     f" their id in the fulltext.")
        data = {
            'id': persona_id,
            'fulltext': core.create_fulltext(persona)
        }
        code = core.sql_update(rs, "core.personas", data)
        count += code
        if code is not 1:
            raise RuntimeError(
                f"Somethings went wrong while updating persona {persona_id}.")
        else:
            print(persona_id, end=" ", flush=True)
        if CHECK:
            persona = core.retrieve_persona(rs, persona_id, ("fulltext",))
            if not str(persona_id) != persona["fulltext"].split(" ", 1)[0]:
                raise AssertionError(f"Persona {persona_id} still has their"
                                     f" id in the fulltext.")
        last_id = persona_id
        persona_id = core.next_persona(rs, persona_id, is_member=False)
    else:
        end = time.time()
        print(f"DONE in {end - start} seconds.")
        print(f"Successfully updated {count} personas up to id {last_id}.")
        if not DRY_RUN:
            pass
        else:
            raise RuntimeError("Aborting DRY_RUN.")
