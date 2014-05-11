#!/usr/bin/env python3

import unittest
from cdedb.backend.common import AuthShim
from cdedb.backend.core import CoreBackend

class TestBackendCommon(unittest.TestCase):
    def test_AuthShim(self):
        backend = CoreBackend("")
        shim = AuthShim(backend)
        self.assertTrue(callable(shim.retrieve_persona_data))
        self.assertTrue(callable(shim.login))
        with self.assertRaises(AttributeError):
            shim.verify_password
