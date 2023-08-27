#!/usr/bin/env python3
# pylint: disable=missing-module-docstring
import io
import sys
import tempfile
import typing
import unittest
from pkgutil import resolve_name
from typing import Any, Callable, ClassVar

import cdedb.common.validation.types as vtypes
from cdedb.backend.core import CoreBackend
from cdedb.backend.event import EventBackend
from cdedb.backend.session import SessionBackend
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
            with tempfile.NamedTemporaryFile("w") as f:
                s = self.get_script(outfile=f.name)
                print("Not writing this to file.")
                print("Not writing this to file either.", file=sys.stderr)
                with s:
                    print("Writing this to file.")
                    print("This too!", file=sys.stderr)
                with open(f.name, "r") as fr:
                    self.check_buffer(
                        fr, self.assertEqual, "Writing this to file.\nThis too!\n",
                        truncate=False)

        expectation = """Not writing this to file.
Not writing this to file either.

================================================================================

Aborting Dry Run! Time taken: 0.000 seconds.

"""
        self.check_buffer(buffer, self.assertEqual, expectation)

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

        # choose SYSLOG_LEVEL, since this is overwritten in the test config
        script = self.get_script()
        self.assertEqual(None, script.config["SYSLOG_LEVEL"])
        self.assertEqual(real_configpath, get_configpath())

        # check overwriting per config argument
        # this takes the options from the real_configpath into account automatically
        configured_script = self.get_script(SYSLOG_LEVEL=42)
        self.assertEqual(42, configured_script.config["SYSLOG_LEVEL"])
        self.assertEqual(real_configpath, get_configpath())
        self.assertEqual(str(configured_script._tempconfig), str({"SYSLOG_LEVEL": 42}))  # pylint: disable=protected-access

        # check overwriting per config file
        # here, we need to set the relevant flags from the real_config manually
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
            f.write("SYSLOG_LEVEL = 42\n")
            f.write(f"DB_HOST = '{real_config['DB_HOST']}'\n")
            f.write(f"DB_PORT = {real_config['DB_PORT']}\n")
            f.write(f"CDB_DATABASE_NAME = '{real_config['CDB_DATABASE_NAME']}'\n")
            f.flush()
            configured_script = self.get_script(configpath=f.name)
            self.assertEqual(42, configured_script.config["SYSLOG_LEVEL"])
            self.assertEqual(real_configpath, get_configpath())

    def test_make_backend(self) -> None:
        # check that the config path stays correct
        real_configpath = get_configpath()
        real_config = TestConfig()

        core = self.script.make_backend("core", proxy=False)
        self.assertTrue(isinstance(core, CoreBackend))
        coreproxy = self.script.make_backend("core", proxy=True)
        self.assertEqual(coreproxy.get_backend_class(), CoreBackend)

        # check setting config options per kwarg
        # this takes the options from the real_configpath into account automatically
        configured_script = self.get_script(LOCKDOWN=42)
        self.assertEqual(
            42,
            configured_script.make_backend("core", proxy=False).conf["LOCKDOWN"])
        self.assertEqual(real_configpath, get_configpath())

        # check setting config options per config file
        # here, we need to set the relevant flags from the real_config manually
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
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

        for realm, backend_name in Script.backend_map.items():
            backend_class = resolve_name(f"cdedb.backend.{realm}.{backend_name}")
            backendproxy = self.script.make_backend(realm, proxy=True)
            self.assertIs(backend_class, backendproxy.get_backend_class())
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
        with tempfile.NamedTemporaryFile("w", suffix=".py") as f:
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

        for realm, frontend_name in Script.frontend_map.items():
            frontend_class = resolve_name(f"cdedb.frontend.{realm}.{frontend_name}")
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

    def test_offline_orgatoken(self) -> None:
        offline_script = self.get_script(CDEDB_OFFLINE_DEPLOYMENT=True)
        event: EventBackend = offline_script.make_backend('event')
        session: SessionBackend = offline_script.make_backend('session', proxy=False)

        token = event.get_orga_token(offline_script.rs(), 1)
        with self.assertRaisesRegex(
                APITokenError, "This API is not available in offline mode."
        ):
            session.lookuptoken(token.get_token_string("abc"), "127.0.0.0")

        with self.assertRaisesRegex(
                ValueError, "May not create new orga token in offline instance."
        ):
            token.id = vtypes.ProtoID(-1)
            event.create_orga_token(offline_script.rs(), token)
