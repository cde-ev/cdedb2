#!/usr/bin/env python3

import sys
from pathlib import Path

sys.path.insert(0, "/cdedb2/")

from cdedb.script import setup

executable, relativ_script_path, *databases = sys.argv

script_path = Path(__file__).absolute().parent.parent / relativ_script_path

with script_path.open() as f:
    script = f.read()

for db in databases or ["cdb"]:

    with setup(
        persona_id=-1,
        dbuser="cdb",
        dbpassword="987654321098765432109876543210",
        dbname=db,
        check_system_user=False,
    )().conn as conn:
        conn.set_session(autocommit=True)

        with conn.cursor() as curr:
            curr.execute(script)
