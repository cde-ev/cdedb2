#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import unittest

from cdedb.backend.core import CoreBackend
from cdedb.common import PrivilegeError, make_proxy


class TestBackendCommon(unittest.TestCase):
    def test_make_proxy(self) -> None:
        backend = CoreBackend()
        proxy = make_proxy(backend)
        self.assertTrue(callable(proxy.get_persona))
        self.assertTrue(callable(proxy.login))
        self.assertTrue(callable(proxy.verify_personas))
        with self.assertRaises(PrivilegeError):
            # pylint: disable=pointless-statement
            proxy.verify_password  # exception in __getitem__
