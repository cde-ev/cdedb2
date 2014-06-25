#!/usr/bin/env python3

"""Management of PostgreSQL database.

The database module specifies the PostgreSQL layout in several ``*.sql``
files and provides python code encapsulating our :py:mod:`psycopg` usage.
"""

#: all available database roles
DATABASE_ROLES = ("cdb_anonymous", "cdb_persona", "cdb_member",
                  "cdb_core_admin", "cdb_cde_admin", "cdb_event_admin",
                  "cdb_ml_admin", "cdb_assembly_admin", "cdb_files_admin",
                  "cdb_admin")
