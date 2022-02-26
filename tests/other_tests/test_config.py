#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import os
import unittest

import pytz

from cdedb.setup.config import Config, SecretsConfig, get_configpath, set_configpath


class TestConfig(unittest.TestCase):
    def test_override(self) -> None:
        # save the actual config path, so we can use this after the test finishes
        current_configpath = get_configpath()

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

        # restore old config path for further tests
        set_configpath(current_configpath)

    def test_caching(self) -> None:
        # this is a regression test
        current_configpath = os.environ.get("CDEDB_CONFIGPATH", "")
        os.environ["CDEDB_CONFIGPATH"] = "tests/ancillary_files/extra_config.py"
        extrasecret = SecretsConfig()
        self.assertEqual(extrasecret["URL_PARAMETER_SALT"], "matrix")
        os.environ["CDEDB_CONFIGPATH"] = current_configpath
        testsecret = SecretsConfig()
        self.assertEqual(testsecret["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO")
