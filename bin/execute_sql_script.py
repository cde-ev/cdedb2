#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/cdedb2/")

from cdedb.script import setup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute a sql script")

    parser.add_argument("--dbuser", default="cdb")
    parser.add_argument("--dbpassword", default="987654321098765432109876543210")
    parser.add_argument("--dbname", default="cdb")
    parser.add_argument("files", nargs="+", type=Path)

    args = parser.parse_args()

    with setup(
        persona_id=-1,
        dbuser=args.dbuser,
        dbpassword=args.dbpassword,
        dbname=args.dbname,
        check_system_user=False,
    )().conn as conn:
        conn.set_session(autocommit=True)

        with conn.cursor() as curr:
            for file in args.files:
                with file.open() as f:
                    curr.execute(f.read())
