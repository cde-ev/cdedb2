#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pkgutil import resolve_name
from typing import Any, Callable, ClassVar

import psycopg2.errorcodes

from cdedb.backend.core import CoreBackend
from cdedb.common import unwrap
from cdedb.config import TestConfig
from cdedb.script import DryRunError, Script, ScriptAtomizer


class TestScript(unittest.TestCase):
    conf: ClassVar[TestConfig]
    script: Script

    @classmethod
    def setUpClass(cls) -> None:
        cls.conf = TestConfig(os.environ['CDEDB_TEST_CONFIGPATH'])

    def setUp(self) -> None:
        self.script = self.get_script()

    def get_script(self, **config: Any) -> Script:
        """This gets an instance of our Script class.

        Note that it is not guaranteed that the database is in a cleanly
        populated state. Tests which rely on specific contents should
        prepare them theirselves.
        """
        return Script(persona_id=-1, dbname=self.conf["CDB_DATABASE_NAME"],
                      dbuser="cdb_admin", check_system_user=False, **config)

    @staticmethod
    def check_buffer(buffer: io.StringIO, assertion: Callable[[str, str], None],
                     value: str) -> None:
        """Chech the buffers content and empty it."""
        buffer.seek(0)
        assertion(value, buffer.read())
        buffer.seek(0)
        buffer.truncate()

    def test_rs_factory(self) -> None:
        rs_factory = self.script.rs
        self.assertTrue(callable(rs_factory))
        self.assertEqual(-1, rs_factory().user.persona_id)
        self.assertEqual(23, rs_factory(23).user.persona_id)

        with self.assertRaises(psycopg2.OperationalError) as cm:
            Script(dbname=self.conf["CDB_DATABASE_NAME"], dbuser="cdb_admin",
                   check_system_user=False, CDB_DATABASE_ROLES="{'cdb_admin': 'abc'}")
        # the vm is german while the postgresql docker image is english
        self.assertTrue(
            ("Passwort-Authentifizierung für Benutzer"
             " »cdb_admin« fehlgeschlagen" in cm.exception.args[0])
            or
            ("password authentication failed for user"
             ' "cdb_admin"' in cm.exception.args[0])
        )

    def test_make_backend(self) -> None:
        core = self.script.make_backend("core", proxy=False)
        self.assertTrue(isinstance(core, CoreBackend))
        coreproxy = self.script.make_backend("core", proxy=True)
        self.assertEqual(coreproxy.get_backend_class(), CoreBackend)
        configured_script = self.get_script(LOCKDOWN=42)
        self.assertEqual(
            42,
            configured_script.make_backend("core", proxy=False).conf["LOCKDOWN"])
        # This way of writing to a temporary file mirrors exactly what happens
        # inside `make_backend`.
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
            f.write("LOCKDOWN = 42")
            f.flush()
            configured_script = self.get_script(configpath=f.name)
            self.assertEqual(
                42,
                configured_script.make_backend("core", proxy=False).conf["LOCKDOWN"])

        for realm, backend_name in Script.backend_map.items():
            backend_class = resolve_name(f"cdedb.backend.{realm}.{backend_name}")
            backendproxy = self.script.make_backend(realm, proxy=True)
            self.assertIs(backend_class, backendproxy.get_backend_class())
            backend = self.script.make_backend(realm, proxy=False)
            self.assertIsInstance(backend, backend_class)

    def test_script_atomizer(self) -> None:
        rs = self.script.rs()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with ScriptAtomizer(rs):
                pass
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            with ScriptAtomizer(rs, dry_run=True):
                pass
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            with ScriptAtomizer(rs, dry_run=False):
                raise DryRunError()
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            # Non-DryRunErrors are not suppressed.
            with self.assertRaises(ValueError):
                with ScriptAtomizer(rs, dry_run=False):
                    raise ValueError()
            self.check_buffer(buffer, self.assertIn,
                              "Error encountered, rolling back! Time taken: ")
            with ScriptAtomizer(rs, dry_run=False):
                pass
            self.check_buffer(buffer, self.assertIn, "Success!")

            minimal_persona = {
                'username': "testUser@example.cde",
                'password_hash': "abcde",
                'display_name': "Test",
                'given_names': "Testuser",
                'family_name': "Dummy",
                'is_cde_realm': False,
                'is_event_realm': False,
                'is_ml_realm': False,
                'is_assembly_realm': False,
                'is_member': False,
                'fulltext': "something"
            }
            insertion_query = (
                f"INSERT INTO core.personas ({', '.join(minimal_persona.keys())})"
                f" VALUES ({', '.join(map(repr, minimal_persona.values()))})"
            )
            selection_query = ("SELECT display_name FROM core.personas"
                               " WHERE family_name = 'Dummy'")
            # Make a change, roll back, then check it hasn't been committed.
            with ScriptAtomizer(rs, dry_run=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(insertion_query)
                    cur.execute(selection_query)
                    self.assertEqual(unwrap(dict(cur.fetchone())), "Test")
            # Now make the change for real.
            with ScriptAtomizer(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(selection_query)
                    self.assertIsNone(cur.fetchone())
                    cur.execute(insertion_query)
            with ScriptAtomizer(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(selection_query)
                    self.assertEqual(unwrap(dict(cur.fetchone())), "Test")
