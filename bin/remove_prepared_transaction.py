#!/usr/bin/env python3

"""Clean up stale prepared transactions.

Having these around messes up the whole system and is really painful as they
are pretty much invisible to the rest of the application.
"""

import argparse

from cdedb.script import Script


def execute_script(dbname: str) -> None:
    with Script(
        dbuser="cdb_admin",
        dbname=dbname,
        check_system_user=False,
    )._conn as conn:
        transactions = conn.tpc_recover()
        for xid in transactions:
            print(f"Removing {xid}")
            conn.tpc_rollback(xid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Drop all prepared transactions. ")

    parser.add_argument("--dbname", "-d", default="cdb")

    args = parser.parse_args()

    execute_script(dbname=args.dbname,)
