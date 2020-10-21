#!/usr/bin/env python3

import argparse
from pathlib import Path

from cdedb.script import setup


def execute_script(file: Path, *, dbuser: str, dbpassword: str, dbname: str):
    with setup(
        persona_id=-1,
        dbuser=dbuser,
        dbpassword=dbpassword,
        dbname=dbname,
        check_system_user=False,
    )().conn as conn:
        conn.set_session(autocommit=True)

        with conn.cursor() as curr:
            with file.open() as f:
                curr.execute(f.read())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute a sql script")

    parser.add_argument("--dbuser", default="cdb")
    parser.add_argument("--dbpassword", default="987654321098765432109876543210")
    parser.add_argument("--dbname", default="cdb")
    parser.add_argument("file", type=Path)

    args = parser.parse_args()

    execute_script(
        args.file, dbuser=args.dbuser, dbpassword=args.dbpassword, dbname=args.dbname
    )
