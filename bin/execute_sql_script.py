#!/usr/bin/env python3

"""This script tries to mimic the psql interface.

It only implements a small subset of possible commands.
Supported: passing a script file, passing a command strings.
Unsupported: psql variables, interactive input, any output.

The script tries to connect to postgres via psycopg.
Host and port are automatically choosen like in the cdedb app itself.
"""

import argparse
from pathlib import Path
from pkgutil import resolve_name
from typing import Union

from cdedb.script import Script


def execute_script(sql_input: Union[Path, str], *, dbuser: str,
                   dbname: str, cursor: str, verbose: int) -> None:
    factory = resolve_name(f"psycopg2.extras:{cursor}") if cursor else None

    with Script(
        persona_id=-1,
        dbuser=dbuser,
        dbname=dbname,
        check_system_user=False,
        cursor=factory,
    )._conn as conn:
        conn.set_session(autocommit=True)

        with conn.cursor() as curr:
            if isinstance(sql_input, Path):
                with sql_input.open() as f:
                    sql_input = f.read()

            curr.execute(sql_input)
            if verbose > 0:
                if verbose > 1:
                    print(curr.query)
                    print(curr.statusmessage)
                if curr.rowcount != -1:
                    for x in curr:
                        print(x)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Execute a sql script", allow_abbrev=False, epilog=__doc__)

    general = parser.add_argument_group("General options")
    general.add_argument("--dbname", "-d", default="cdb")
    general.add_argument("--verbose", "-v", action="count", default=0)
    group = general.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", type=Path)
    group.add_argument("--command", "-c")

    connection = parser.add_argument_group("Connection options")
    connection.add_argument("--username", "-U", default="cdb")
    connection.add_argument("--cursor", default=None)

    args = parser.parse_args()

    execute_script(
        args.file or args.command,
        dbuser=args.username,
        dbname=args.dbname,
        cursor=args.cursor,
        verbose=args.verbose,
    )
