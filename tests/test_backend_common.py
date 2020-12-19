#!/usr/bin/env python3

import unittest
from cdedb.config import BasicConfig
from cdedb.common import make_proxy, PrivilegeError
from cdedb.backend.core import CoreBackend

_BASICCONF = BasicConfig()


class TestBackendCommon(unittest.TestCase):
    def test_make_proxy(self):
        backend = CoreBackend()
        proxy = make_proxy(backend)
        self.assertTrue(callable(proxy.get_persona))
        self.assertTrue(callable(proxy.login))
        self.assertTrue(callable(proxy.get_realms_multi))
        with self.assertRaises(PrivilegeError):
            proxy.verify_password
