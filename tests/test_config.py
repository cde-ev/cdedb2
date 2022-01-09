#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import os
import unittest

import pytz

from cdedb.config import BasicConfig, Config, SecretsConfig


class TestConfig(unittest.TestCase):
    def test_override(self) -> None:
        basic = BasicConfig()
        self.assertEqual(basic["DEFAULT_TIMEZONE"], pytz.timezone('CET'))
        config = Config(None)
        self.assertIn(config["DB_PORT"], {6432, 5432})
        self.assertEqual(config["CDB_DATABASE_NAME"], os.environ['CDEDB_TEST_DATABASE'])
        extraconfig = Config("tests/ancillary_files/extra_config.py")
        self.assertEqual(extraconfig["DB_PORT"], 42)
        self.assertEqual(extraconfig["CDB_DATABASE_NAME"], "skynet")
        secret = SecretsConfig(None)
        self.assertEqual(secret["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO")
        extrasecret = SecretsConfig("tests/ancillary_files/extra_config.py")
        self.assertEqual(extrasecret["URL_PARAMETER_SALT"], "matrix")

    def test_caching(self) -> None:
        # this is a regression test
        BasicConfig()
        extrasecret = SecretsConfig("tests/ancillary_files/extra_config.py")
        self.assertEqual(extrasecret["URL_PARAMETER_SALT"], "matrix")
        testsecret = SecretsConfig()
        self.assertEqual(testsecret["URL_PARAMETER_SALT"], "aoeuidhtns9KT6AOR2kNjq2zO")
