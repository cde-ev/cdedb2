#!/usr/bin/env python3

import unittest
from cdedb.config import BasicConfig, Config, SecretsConfig

class TestConfig(unittest.TestCase):
    def test_override(self):
        basic = BasicConfig()
        self.assertEqual(6432, basic.DB_PORT)
        config = Config(None)
        self.assertEqual(6432, config.DB_PORT)
        self.assertEqual("cdb", config.CDB_DATABASE_NAME)
        extraconfig = Config("test/ancillary_files/extra_config.py")
        self.assertEqual(6432, extraconfig.DB_PORT)
        self.assertEqual("skynet", extraconfig.CDB_DATABASE_NAME)
        secret = SecretsConfig(None)
        self.assertEqual("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3", secret.ML_SCRIPT_KEY)
        extrasecret = SecretsConfig("test/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret.ML_SCRIPT_KEY)

    def test_caching(self):
        ## this is a regression test
        basic = BasicConfig()
        extrasecret = SecretsConfig("test/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret.ML_SCRIPT_KEY)
        testsecret = SecretsConfig(basic.TESTCONFIG_PATH)
        self.assertEqual("c1t2w3r4n5v6l6s7z8ap9u0k1y2i2x3", testsecret.ML_SCRIPT_KEY)
