#!/usr/bin/env python3

import unittest
import io
import tempfile
from contextlib import redirect_stdout

import psycopg2.errorcodes

from cdedb.common import unwrap
from cdedb.script import setup, make_backend, Script, DryRunError
from cdedb.backend.core import CoreBackend


class TestScript(unittest.TestCase):
    @staticmethod
    def get_rs():
        return setup(persona_id=-1, dbname="cdb_test", dbuser="cdb_admin",
                           dbpassword="9876543210abcdefghijklmnopqrst",
                           check_system_user=False)

    @staticmethod
    def check_buffer(buffer, assertion, value):
        buffer.seek(0)
        assertion(value, buffer.read())
        buffer.seek(0)

    def test_setup(self):
        rs_factory = self.get_rs()
        self.assertTrue(callable(rs_factory))
        self.assertEqual(-1, rs_factory().user.persona_id)
        self.assertEqual(23, rs_factory(23).user.persona_id)

        # TODO replace with psycopg2.error.InvalidPassword in psycopg2 2.8
        with self.assertRaises(psycopg2.OperationalError) as cm:
            setup(-1, dbname="cdb_test", dbuser="cdb_admin", dbpassword="abc",
                  check_system_user=False)
        self.assertEqual(
            cm.exception.pgcode, psycopg2.errorcodes.INVALID_PASSWORD)

    def test_make_backend(self):
        core = make_backend("core", proxy=False)
        self.assertTrue(isinstance(core, CoreBackend))
        coreproxy = make_backend("core", proxy=True)
        self.assertEqual(coreproxy._get_backend_class(), CoreBackend)
        self.assertEqual(
            make_backend("core", proxy=False, LOCKDOWN=42).conf["LOCKDOWN"], 42)
        # This way of writing to a tempporary file mirrors exactly what happens
        # inside `make_backend`.
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
            f.write("LOCKDOWN = 42")
            f.flush()
            self.assertEqual(
                make_backend("core", proxy=False,
                             configpath=f.name).conf["LOCKDOWN"], 42)

    def test_script_atomizer(self):
        rs = self.get_rs()()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with Script(rs):
                pass
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            with Script(rs, dry_run=True):
                pass
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            with Script(rs, dry_run=False):
                raise DryRunError()
            self.check_buffer(buffer, self.assertIn,
                              "Aborting Dry Run! Time taken: ")
            # Non-DryRunErrors are not suppressed.
            with self.assertRaises(ValueError):
                with Script(rs, dry_run=False):
                    raise ValueError()
            self.check_buffer(buffer, self.assertIn,
                              "Error encountered, rolling back! Time taken: ")
            with Script(rs, dry_run=False):
                pass
            self.check_buffer(buffer, self.assertIn, "Success!")

            # Make a change, roll back, then check it hasn't been committed.
            with Script(rs, dry_run=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE core.personas SET display_name = 'Test'"
                        " WHERE id = 1")
                    cur.execute(
                        "SELECT display_name FROM core.personas WHERE id = 1")
                    self.assertEqual(unwrap(dict(cur.fetchone())), "Test")
            # Now make the change for real.
            with Script(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT display_name FROM core.personas WHERE id = 1")
                    self.assertNotEqual(unwrap(dict(cur.fetchone())), "Test")
                    cur.execute(
                        "UPDATE core.personas SET display_name = 'Test'"
                        " WHERE id = 1")
            with Script(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT display_name FROM core.personas WHERE id = 1")
                    self.assertEqual(unwrap(dict(cur.fetchone())), "Test")
