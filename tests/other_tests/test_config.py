#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import pathlib
import unittest
from typing import ClassVar

from cdedb_setup.config import Config, SecretsConfig, get_configpath, set_configpath


class TestConfig(unittest.TestCase):

    real_config_path: ClassVar[pathlib.Path]

    @classmethod
    def setUpClass(cls) -> None:
        # store the real config path, so we can reset it after each test
        cls.real_config_path = get_configpath()

    def tearDown(self) -> None:
        # reset the config path
        set_configpath(self.real_config_path)

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
