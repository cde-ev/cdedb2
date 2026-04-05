#!/usr/bin/env python3
import logging
import pathlib
import subprocess
import tempfile
import unittest
from typing import ClassVar

from cdedb.config import (
    Config,
    SecretsConfig,
    get_configpath,
    set_configpath,
)

_LOGGER = logging.getLogger(__name__)


def reset_config(configpath: pathlib.Path) -> None:
    # This is technically wrong, since it overwrites any kwarg overrides previously given.
    #  We just assume that this won't happen in order to run these tests.
    Config()._init_once()
    set_configpath(configpath)


class TestConfig(unittest.TestCase):
    real_config_path: ClassVar[pathlib.Path]
    config = Config()
    secrets = SecretsConfig()

    @classmethod
    def setUpClass(cls) -> None:
        # store the real config path, so we can reset it after each test
        cls.real_config_path = get_configpath()

    def setUp(self) -> None:
        if (
            self.config._temp_config_path is not None
            or self.config._context_manager_overrides
        ):
            self.fail("Started config test with active config overrides.")

    def tearDown(self) -> None:
        reset_config(self.real_config_path)

    def test_override(self) -> None:
        # check config default values
        config = Config()
        self.assertIn(config["DB_PORT"], {6432, 5432})

        # check secret config default values
        secret = SecretsConfig()
        self.assertEqual(secret["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO")

        # override default values by providing a config path
        set_configpath("tests/ancillary_files/extra_config.py")

        # check config override
        extraconfig = Config()
        self.assertEqual(extraconfig["DB_PORT"], 42)
        self.assertEqual(extraconfig["CDB_DATABASE_NAME"], "skynet")

        # check secret config override
        extrasecret = SecretsConfig()
        self.assertEqual(extrasecret["URL_PARAMETER_SALT"], "matrix")

    def test_override_new(self) -> None:
        def check_config_defaults() -> None:
            # self.assertIs(self.config, NewConfig())
            # check config default values
            self.assertIn(self.config["DB_PORT"], {6432, 5432})
            self.assertEqual(self.config["CDB_DATABASE_NAME"][:-1], "cdb_test_")

        def check_secrets_defaults() -> None:
            # self.assertIs(self.secrets, NewSecretsConfig())
            # check secret config default values
            self.assertEqual(
                self.secrets["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO"
            )

        def check_config_overrides() -> None:
            # self.assertIs(self.config, NewConfig())
            self.assertEqual(self.config["DB_PORT"], 42)
            self.assertEqual(self.config["CDB_DATABASE_NAME"], "skynet")

        def check_secrets_overrides() -> None:
            # self.assertIs(self.secrets, NewSecretsConfig())
            self.assertEqual(self.secrets["URL_PARAMETER_SALT"], "matrix")

        check_config_defaults()
        check_secrets_defaults()

        # Check override via local config path.
        #  (This replaces the config path set for the testsuite.)

        override_path = pathlib.Path("tests/ancillary_files/extra_config.py")

        with self.config.with_overrides(local_config_path=override_path):
            check_config_overrides()
            # The override config also adjusts the secrets config path.
            check_secrets_overrides()

        check_config_defaults()
        check_secrets_defaults()

        # Check override via temp file (via kwarg override).
        #  (This keeps the local config path set for the testsuite but takes precedence.)

        with self.config.with_overrides(TEMP_CONFIG_PATH=override_path):
            check_config_overrides()
            # The override config also adjusts the secrets config path.
            check_secrets_overrides()

        check_config_defaults()
        check_secrets_defaults()

        with tempfile.NamedTemporaryFile("w", encoding="utf8", suffix=".py") as f:
            with self.config.with_overrides(TEMP_CONFIG_PATH=pathlib.Path(f.name)):
                # File is still empty.
                check_config_defaults()
                check_secrets_defaults()

                f.write(override_path.read_text(encoding="utf8"))
                f.flush()

                # config ist automatically reloaded on item access.
                check_config_overrides()
                check_secrets_overrides()

            check_config_defaults()
            check_secrets_defaults()

        check_config_defaults()
        check_secrets_defaults()

        # Check override via kwargs.
        #  (This keeps the local config path set for the testsuite but takes precedence.)

        with self.config.with_overrides(DB_PORT=42, CDB_DATABASE_NAME="skynet"):
            check_config_overrides()
            check_secrets_defaults()

        with self.config.with_overrides(URL_PARAMETER_SALT="matrix"):
            check_config_defaults()
            check_secrets_overrides()

        with self.config.with_overrides(
            DB_PORT=42, CDB_DATABASE_NAME="skynet", URL_PARAMETER_SALT="matrix"
        ):
            check_config_overrides()
            check_secrets_overrides()

        check_config_defaults()
        check_secrets_defaults()

    def test_caching(self) -> None:
        current_configpath = get_configpath()
        # the new config configures itself as secret config override!
        set_configpath("tests/ancillary_files/extra_config.py")

        # check that the secrets config was overridden
        extrasecret = SecretsConfig()
        self.assertEqual(extrasecret["URL_PARAMETER_SALT"], "matrix")

        # check that everything works fine if we reset to the previous configpath
        set_configpath(current_configpath)
        testsecret = SecretsConfig()
        self.assertEqual(testsecret["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO")

    def test_production_secrets(self) -> None:
        production_vm_marker = pathlib.Path("/PRODUCTIONVM")

        dev_secrets = SecretsConfig()
        self.assertIn("URL_PARAMETER_SALT", dev_secrets)

        try:
            subprocess.call(["sudo", "touch", production_vm_marker])
            production_secrets = SecretsConfig()
            self.assertNotIn("URL_PARAMETER_SALT", production_secrets)
        finally:
            subprocess.call(["sudo", "rm", production_vm_marker])
