#!/usr/bin/env python3

import unittest
from cdedb.config import BasicConfig
from cdedb.common import ProxyShim
from cdedb.backend.core import CoreBackend

_BASICCONF = BasicConfig()

class TestBackendCommon(unittest.TestCase):
    def test_ProxyShim(self):
        backend = CoreBackend(_BASICCONF.REPOSITORY_PATH / _BASICCONF.TESTCONFIG_PATH)
        shim = ProxyShim(backend)
        self.assertTrue(callable(shim.get_persona))
        self.assertTrue(callable(shim.login))
        self.assertTrue(callable(shim.get_realms_multi))
        with self.assertRaises(AttributeError):
            shim.verify_password
