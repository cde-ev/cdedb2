#!/usr/bin/env -S uv run
"""Generic script to give trial membership to a bunch of people at once.

Pass individual IDs as arguments or ranges as `a:b` which will yield all ids
from a to b, inclusive.
"""

from cdedb.script import Script

import sys

# setup

script = Script(dbuser="cdb_admin")
rs = script.rs()
core = script.make_core_backend()

persona_ids = []
for x in sys.argv[1:]:
    if ":" in x:
        a, b = x.split(":", maxsplit=1)
        persona_ids.extend(range(int(a), int(b) + 1))
    else:
        persona_ids.append(int(x))

# work

result = 0

with script:
    print(f"Persona IDs: {", ".join(map(str, persona_ids))}")
    for persona_id in persona_ids:
        result += core.change_membership_easy_mode(rs, persona_id, trial_member=True)

    print(f"Set trialmembership for {result} personas.")

    if result != len(persona_ids):
        raise ValueError
