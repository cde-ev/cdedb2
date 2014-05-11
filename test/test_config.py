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
        self.assertEqual("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", secret.SESSION_LOOKUP_KEY)
        extrasecret = SecretsConfig("test/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret.SESSION_LOOKUP_KEY)

    def test_caching(self):
        ## this is a regression test
        basic = BasicConfig()
        extrasecret = SecretsConfig("test/ancillary_files/extra_config.py")
        self.assertEqual("matrix", extrasecret.SESSION_LOOKUP_KEY)
        testsecret = SecretsConfig(basic.TESTCONFIG_PATH)
        self.assertEqual("a1o2e3u4i5d6h7t8n9s0a1o2e3u4i5", testsecret.SESSION_LOOKUP_KEY)
