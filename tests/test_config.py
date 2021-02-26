#!/usr/bin/env python3
import os
import unittest

import pytz

from cdedb.config import BasicConfig, Config, SecretsConfig


class TestConfig(unittest.TestCase):
    def test_override(self) -> None:
        basic = BasicConfig()
        self.assertEqual(pytz.timezone('CET'), basic["DEFAULT_TIMEZONE"])
        config = Config(None)
        self.assertEqual(6432, config["DB_PORT"])
        self.assertEqual(os.environ['CDEDB_TEST_DATABASE'], config["CDB_DATABASE_NAME"])
        extraconfig = Config("tests/ancillary_files/extra_config.py")
        self.assertEqual(42, extraconfig["DB_PORT"])
        self.assertEqual("skynet", extraconfig["CDB_DATABASE_NAME"])
        secret = SecretsConfig(None)
        self.assertEqual("aoeuidhtns9KT6AOR2kNjq2zO", secret["URL_PARAMETER_SALT"])
        extrasecret = SecretsConfig("tests/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret["URL_PARAMETER_SALT"])

    def test_caching(self) -> None:
        # this is a regression test
        basic = BasicConfig()
        extrasecret = SecretsConfig("tests/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret["URL_PARAMETER_SALT"])
        testsecret = SecretsConfig()
        self.assertEqual("aoeuidhtns9KT6AOR2kNjq2zO", testsecret["URL_PARAMETER_SALT"])
