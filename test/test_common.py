#!/usr/bin/env python3

import unittest
from cdedb.common import extract_realm, extract_roles
import cdedb.database.constants as const

class TestCommon(unittest.TestCase):
    def test_realm_extraction(self):
        with self.assertRaises(ValueError):
            extract_realm(-328)

    def test_extract_roles(self):
        self.assertEqual({
            "anonymous", "persona", "formermember", "member", "searchmember",
            "ml_user", "assembly_user", "event_user",},
            extract_roles(0, const.PersonaStati.searchmember))
        self.assertLess(5, len(extract_roles(
            2**32-1, const.PersonaStati.searchmember)))
        with self.assertRaises(TypeError):
            extract_roles("garbage", 0)
