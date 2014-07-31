#!/usr/bin/env python3

import os
import unittest
from cdedb.config import BasicConfig
from cdedb.backend.common import AuthShim
from cdedb.backend.core import CoreBackend

_BASICCONF = BasicConfig()

class TestBackendCommon(unittest.TestCase):
    def test_AuthShim(self):
        backend = CoreBackend(os.path.join(_BASICCONF.REPOSITORY_PATH,
                                           _BASICCONF.TESTCONFIG_PATH))
        shim = AuthShim(backend)
        self.assertTrue(callable(shim.retrieve_persona_data))
        self.assertTrue(callable(shim.login))
        with self.assertRaises(AttributeError):
            shim.verify_password
