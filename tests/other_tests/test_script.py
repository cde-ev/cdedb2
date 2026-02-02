#!/usr/bin/env python3
import io
import sys
import tempfile
import typing
import unittest
from collections.abc import Callable
from typing import Any, ClassVar

from cdedb.backend.core import CoreBackend
from cdedb.cli.util import redirect_to_file
from cdedb.common import unwrap
from cdedb.common.exceptions import APITokenError
from cdedb.config import TestConfig, get_configpath
from cdedb.frontend.core import CoreFrontend
from cdedb.script import DryRunError, Script, ScriptAtomizer


class TestScript(unittest.TestCase):
    conf: ClassVar[TestConfig]
    script: Script

    @classmethod
    def setUpClass(cls) -> None:
        cls.conf = TestConfig()

    def setUp(self) -> None:
        self.script = self.get_script()

    @staticmethod
    def get_script(**config: Any) -> Script:
        """This gets an instance of our Script class.

        Note that it is not guaranteed that the database is in a cleanly
        populated state. Tests which rely on specific contents should
        prepare them theirselves.
        """
        return Script(persona_id=-1, dbuser="cdb_admin", check_system_user=False,
                      **config)

    @staticmethod
    def check_buffer(buffer: typing.IO[str], assertion: Callable[[str, str], None],
                     value: str, truncate: bool = True) -> None:
        """Check the buffer's content and empty it."""
        buffer.seek(0)  # go to start of buffer
        assertion(value, buffer.read())
        buffer.seek(0)  # go back to start of buffer
        if truncate:
            buffer.truncate()  # cut off content after current position -> empty buffer

    def test_outfile(self) -> None:
        buffer = io.StringIO()
        with redirect_to_file(buffer):
            with tempfile.NamedTemporaryFile("w", encoding="utf-8") as f:
                s = self.get_script(outfile=f.name)
                print("Not writing this to file.")
                print("Not writing this to file either.", file=sys.stderr)
                with s:
                    print("Writing this to file.")
                    print("This too!", file=sys.stderr)
                with open(f.name, encoding="utf-8") as fr:
                    self.check_buffer(
                        fr, self.assertEqual, "Writing this to file.\nThis too!\n",
                        truncate=False)

        expectation = "Not writing this to file.\nNot writing this to file either."
        self.check_buffer(buffer, self.assertIn, expectation)

    def test_rs_factory(self) -> None:
        rs_factory = self.script.rs
        self.assertTrue(callable(rs_factory))
        self.assertEqual(-1, rs_factory().user.persona_id)
        self.assertEqual(23, rs_factory(23).user.persona_id)
        self.assertIs(rs_factory(42), rs_factory(42))

        with self.assertRaises(ValueError) as cm:
            Script(dbuser="cdb_admin", check_system_user=False,
                   CDB_DATABASE_ROLES="{'cdb_admin': 'abc'}")
        msg = "Override secret config options via kwarg is not possible."
        self.assertIn(msg, cm.exception.args[0])

    def test_config_overwrite(self) -> None:
        # check that the config path stays correct
        real_configpath = get_configpath()
        real_config = TestConfig()

        # choose EVENT_ARCHIVAL_BALANCE_CUTOFF, since this is overwritten in the test config
        script = self.get_script()
        self.assertEqual(0, script.config["EVENT_ARCHIVAL_BALANCE_CUTOFF"])
        self.assertEqual(real_configpath, get_configpath())
        self.assertTrue(script.config._is_frozen)

        # check overwriting per config argument
        # this takes the options from the real_configpath into account automatically
        configured_script = self.get_script(EVENT_ARCHIVAL_BALANCE_CUTOFF=42)
        self.assertEqual(42, configured_script.config["EVENT_ARCHIVAL_BALANCE_CUTOFF"])
        self.assertEqual(real_configpath, get_configpath())
        self.assertEqual(str(configured_script._tempconfig),
                         str({"EVENT_ARCHIVAL_BALANCE_CUTOFF": 42}))
        self.assertTrue(configured_script.config._is_frozen)

        self.get_script(some_key="string value")

        # check overwriting per config file
        # here, we need to set the relevant flags from the real_config manually
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8") as f:
            f.write("EVENT_ARCHIVAL_BALANCE_CUTOFF = 42\n")
            f.write(f"DB_HOST = '{real_config['DB_HOST']}'\n")
            f.write(f"DB_PORT = {real_config['DB_PORT']}\n")
            f.write(f"CDB_DATABASE_NAME = '{real_config['CDB_DATABASE_NAME']}'\n")
            f.flush()
            configured_script = self.get_script(configpath=f.name)
            self.assertEqual(
                42, configured_script.config["EVENT_ARCHIVAL_BALANCE_CUTOFF"])
            self.assertEqual(real_configpath, get_configpath())
            self.assertTrue(configured_script.config._is_frozen)

        # check that other configs are not marked as frozen
        self.assertFalse(TestConfig()._is_frozen)

    def test_make_backend(self) -> None:
        # check that the config path stays correct
        real_configpath = get_configpath()
        real_config = TestConfig()

        core = self.script.make_core_backend(proxy=False)
        self.assertTrue(isinstance(core, CoreBackend))
        coreproxy = self.script.make_core_backend(proxy=True)
        self.assertEqual(coreproxy.get_backend_class(), CoreBackend)  # type: ignore[attr-defined]

        # check setting config options per kwarg
        # this takes the options from the real_configpath into account automatically
        configured_script = self.get_script(LOCKDOWN=42)
        self.assertEqual(
            42,
            configured_script.make_backend("core", proxy=False).conf["LOCKDOWN"])
        self.assertEqual(real_configpath, get_configpath())

        # check setting config options per config file
        # here, we need to set the relevant flags from the real_config manually
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8") as f:
            f.write("LOCKDOWN = 42\n")
            f.write(f"DB_HOST = '{real_config['DB_HOST']}'\n")
            f.write(f"DB_PORT = {real_config['DB_PORT']}\n")
            f.write(f"CDB_DATABASE_NAME = '{real_config['CDB_DATABASE_NAME']}'\n")
            f.flush()
            configured_script = self.get_script(configpath=f.name)
            self.assertEqual(
                42,
                configured_script.make_backend("core", proxy=False).conf["LOCKDOWN"])
            self.assertEqual(real_configpath, get_configpath())

        for realm, backend_class in Script.backend_map.items():
            backendproxy = self.script.make_backend(realm, proxy=True)
            self.assertIs(backend_class, backendproxy.get_backend_class())  # type: ignore[attr-defined]
            self.assertIs(backendproxy, self.script.make_backend(realm, proxy=True))
            backend = self.script.make_backend(realm, proxy=False)
            self.assertIsInstance(backend, backend_class)
            self.assertIs(backend, self.script.make_backend(realm, proxy=False))

    def test_make_frontend(self) -> None:
        # check that the config path stays correct.
        real_configpath = get_configpath()
        real_config = TestConfig()

        core = self.script.make_frontend("core")
        self.assertIsInstance(core, CoreFrontend)

        # check setting config options per kwarg
        # this takes the options from the real_configpath into account automatically
        configured_script = self.get_script(LOCKDOWN=42)
        self.assertEqual(42, configured_script.make_frontend("core").conf["LOCKDOWN"])
        self.assertEqual(real_configpath, get_configpath())

        # check setting config options per config file
        # here, we need to set the relevant flags from the real_config manually
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8") as f:
            f.write("LOCKDOWN = 42\n")
            f.write(f"DB_HOST = '{real_config['DB_HOST']}'\n")
            f.write(f"DB_PORT = {real_config['DB_PORT']}\n")
            f.write(f"CDB_DATABASE_NAME = '{real_config['CDB_DATABASE_NAME']}'\n")
            f.flush()
            configured_script = self.get_script(configpath=f.name)
            self.assertEqual(
                42,
                configured_script.make_frontend("core").conf["LOCKDOWN"])
            self.assertEqual(real_configpath, get_configpath())

        for realm, frontend_class in Script.frontend_map.items():
            frontend = self.script.make_frontend(realm)
            self.assertIsInstance(frontend, frontend_class)
            self.assertIs(frontend, self.script.make_frontend(realm))

    def test_script_atomizer(self) -> None:
        rs = self.script.rs()
        buffer = io.StringIO()
        with redirect_to_file(buffer):
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

            insertion_query = (
                "INSERT INTO core.cron_store"  # arbitrary, small table
                " (title, store) VALUES ('Test', '{}')"
            )
            selection_query = ("SELECT title FROM core.cron_store"
                               " WHERE title = 'Test'")
            # Make a change, roll back, then check it hasn't been committed.
            with ScriptAtomizer(rs, dry_run=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(insertion_query)
                    cur.execute(selection_query)
                    self.assertEqual(unwrap(dict(cur.fetchone() or {})), "Test")
            # Now make the change for real.
            with ScriptAtomizer(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(selection_query)
                    self.assertIsNone(cur.fetchone())
                    cur.execute(insertion_query)
            with ScriptAtomizer(rs, dry_run=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(selection_query)
                    self.assertEqual(unwrap(dict(cur.fetchone() or {})), "Test")

    def test_offline_orgatoken(self) -> None:
        offline_script = self.get_script(CDEDB_OFFLINE_DEPLOYMENT=True)
        event = offline_script.make_event_backend(proxy=True)
        session = offline_script.make_session_backend(proxy=False)

        token = event.get_orga_token(offline_script.rs(), 1)
        with self.assertRaisesRegex(
                APITokenError, "This API is not available in offline mode.",
        ):
            session.lookuptoken(token.get_token_string("abc"), "127.0.0.0")

        with self.assertRaisesRegex(
                ValueError, "May not create new orga token in offline instance.",
        ):
            data = token.to_database()
            del data["id"]
            event.create_orga_token(offline_script.rs(), data)
