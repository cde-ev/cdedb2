#!/usr/bin/env python3

import unittest
import psycopg2.extensions
import os.path
from cdedb.database.connection import (
    connection_pool_factory, IrradiatedConnection, Atomizer)
from cdedb.config import BasicConfig, Config, SecretsConfig

_BASICCONF = BasicConfig()
_CONF = Config()
_SECRECTSCONF = SecretsConfig()

class TestDatabase(unittest.TestCase):
    def test_instant_connection(self):
        factory = connection_pool_factory(
            _CONF["CDB_DATABASE_NAME"],
            ("cdb_anonymous", "cdb_persona", "cdb_admin"),
            _SECRECTSCONF, _CONF["DB_PORT"])
        with factory["cdb_persona"] as conn:
            self.assertIsInstance(conn, psycopg2.extensions.connection)
            self.assertIsInstance(conn, IrradiatedConnection)
        with self.assertRaises(ValueError):
            factory["nonexistentrole"]

    def test_less_users(self):
        factory = connection_pool_factory(
            _CONF["CDB_DATABASE_NAME"], ("cdb_anonymous", "cdb_admin"),
            _SECRECTSCONF, _CONF["DB_PORT"])
        with self.assertRaises(ValueError):
            factory["cdb_persona"]

    def test_atomizer(self):
        factory = connection_pool_factory(
            _CONF["CDB_DATABASE_NAME"],
            ("cdb_persona",), _SECRECTSCONF, _CONF["DB_PORT"])
        conn = factory["cdb_persona"]
        class Tmp:
            def __init__(self, conn):
                self._conn = conn
                self.conn = conn
        rs = Tmp(conn)
        with Atomizer(rs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM core.personas")
            with rs.conn as nested_conn:
                with nested_conn.cursor() as nested_cur:
                    nested_cur.execute("SELECT * FROM core.sessions")
            self.assertNotEqual(psycopg2.extensions.STATUS_READY,
                                nested_conn.status)
        self.assertEqual(psycopg2.extensions.STATUS_READY, nested_conn.status)

    def test_suppressed_exception(self):
        factory = connection_pool_factory(
            _CONF["CDB_DATABASE_NAME"],
            ("cdb_admin",), _SECRECTSCONF, _CONF["DB_PORT"])
        conn = factory["cdb_admin"]
        class Tmp:
            def __init__(self, conn):
                self._conn = conn
                self.conn = conn
        rs = Tmp(conn)
        with self.assertRaises(RuntimeError):
            with Atomizer(rs) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM core.personas")
                ## don't do this at home
                ## this is an anti-pattern
                try:
                    with rs.conn as nested_conn:
                        with nested_conn.cursor() as nested_cur:
                            nested_cur.execute("UPDATE core.personas SET display_name = 'ABBA (random name)'")
                            raise ValueError("test error")
                except ValueError:
                    pass
        with rs.conn as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT display_name FROM core.personas")
                l = cur.fetchall()
                self.assertFalse(any(x['display_name'] == "ABBA (random name)" for x in l))
