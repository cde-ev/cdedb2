#!/usr/bin/env python3

import unittest
from cdedb.common import extract_realm, extract_global_privileges

class TestCommon(unittest.TestCase):
    def test_realm_extraction(self):
        with self.assertRaises(ValueError):
            extract_realm(-328)

    def test_extract_global_privileges(self):
        self.assertEqual({"anonymous", "persona"}, extract_global_privileges(0, -1))
        self.assertEqual({"anonymous", "persona", "member"}, extract_global_privileges(0, 0))
        self.assertLess(5, len(extract_global_privileges(2**32-1, 0)))
        with self.assertRaises(TypeError):
            extract_global_privileges("garbage", 0)
