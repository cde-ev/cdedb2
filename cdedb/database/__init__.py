#!/usr/bin/env python3

"""Management of PostgreSQL database.

The database module specifies the PostgreSQL layout in several ``*.sql``
files and provides python code encapsulating our :py:mod:`psycopg` usage.
"""

#: all available database roles
DATABASE_ROLES = ("cdb_anonymous", "cdb_persona", "cdb_member", "cdb_admin")
