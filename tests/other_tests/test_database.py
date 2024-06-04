#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import unittest
from typing import Any, cast

import psycopg2.extensions

from cdedb.backend.common import DatabaseLock, Silencer, _affirm_atomized_context
from cdedb.common import RequestState
from cdedb.config import Config, SecretsConfig
from cdedb.database.connection import (
    Atomizer, ConnectionContainer, IrradiatedConnection, connection_pool_factory,
)


class TestDatabase(unittest.TestCase):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.config = Config()
        self.secrets = SecretsConfig()

    def test_instant_connection(self) -> None:
        factory = connection_pool_factory(
            self.config["CDB_DATABASE_NAME"],
            ("cdb_anonymous", "cdb_persona", "cdb_admin"),
            self.secrets, self.config["DB_HOST"], self.config["DB_PORT"])
        with factory["cdb_persona"] as conn:
            self.assertIsInstance(conn, psycopg2.extensions.connection)
            self.assertIsInstance(conn, IrradiatedConnection)
        with self.assertRaises(ValueError):
            # pylint: disable=pointless-statement
            factory["nonexistentrole"]  # exception in __getitem__

    def test_less_users(self) -> None:
        factory = connection_pool_factory(
            self.config["CDB_DATABASE_NAME"], ("cdb_anonymous", "cdb_admin"),
            self.secrets, self.config["DB_HOST"], self.config["DB_PORT"])
        with self.assertRaises(ValueError):
            # pylint: disable=pointless-statement
            factory["cdb_persona"]  # exception in __getitem__

    def test_atomizer(self) -> None:
        factory = connection_pool_factory(
            self.config["CDB_DATABASE_NAME"], ("cdb_persona",), self.secrets,
            self.config["DB_HOST"], self.config["DB_PORT"])
        conn = factory["cdb_persona"]

        rs = ConnectionContainer()
        rs.conn = rs._conn = conn
        with Atomizer(rs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM core.personas")
            with rs.conn as nested_conn:
                with nested_conn.cursor() as nested_cur:
                    nested_cur.execute("SELECT * FROM core.sessions")
            self.assertNotEqual(psycopg2.extensions.STATUS_READY,
                                nested_conn.status)
        self.assertEqual(psycopg2.extensions.STATUS_READY, nested_conn.status)

        rs = cast(RequestState, rs)

        with self.assertRaises(RuntimeError):
            _affirm_atomized_context(rs)
        with Atomizer(rs):
            _affirm_atomized_context(rs)

        # The following context managers raise an error during __enter__.
        #  The pass is required syntactically, but never run.
        with Atomizer(rs):
            with self.assertRaises(RuntimeError):
                with DatabaseLock(rs):
                    pass  # pragma: no cover

        # Add missing attribute of actual RequestState.
        rs.is_quiet = False

        with self.assertRaises(RuntimeError):
            with Silencer(rs):
                pass  # pragma: no cover

        with Atomizer(rs):
            with Silencer(rs):
                with self.assertRaises(RuntimeError):
                    with Silencer(rs):
                        pass  # pragma: no cover

    def test_suppressed_exception(self) -> None:
        factory = connection_pool_factory(
            self.config["CDB_DATABASE_NAME"], ("cdb_admin",), self.secrets,
            self.config["DB_HOST"], self.config["DB_PORT"])
        conn = factory["cdb_admin"]

        rs = ConnectionContainer()
        rs.conn = rs._conn = conn
        with self.assertRaises(RuntimeError):
            with Atomizer(rs) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM core.personas")
                # don't do this at home
                # this is an anti-pattern
                try:
                    with rs.conn as nested_conn:
                        with nested_conn.cursor() as nested_cur:
                            nested_cur.execute("UPDATE core.personas SET display_name"
                                               " = 'ABBA (random name)'")
                            raise ValueError("test error")
                except ValueError:
                    pass
        with rs.conn as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT display_name FROM core.personas")
                result = cur.fetchall()
                self.assertFalse(any(
                    x['display_name'] == "ABBA (random name)" for x in result))
