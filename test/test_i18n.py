#!/usr/bin/env python3

import unittest
from cdedb.internationalization import i18n_factory, I18N

class TestI18n(unittest.TestCase):
    def test_I18N(self):
        i = I18N()
        self.assertEqual("not so long test string", i("not so long test string"))
        i = I18N()
        i.add_string("foo", "bar")
        self.assertEqual("bar", i("foo"))
        self.assertEqual("no i18n", i("no i18n"))
        i = I18N()
        i.add_regex("fo*([0-9]+)42(.*)", r"bar\1xx\2")
        self.assertEqual("bar12xx", i("fo1242"))
        self.assertEqual("bar3333xx", i("foooooooo333342"))
        self.assertEqual("bar12xx to it", i("fo1242 to it"))
        i = I18N()
        i.add_string("foo", "bar")
        i.add_regex("foo", r"rab")
        self.assertEqual("bar", i("foo"))

    def test_factory(self):
        i = i18n_factory()
        self.assertEqual("not so long test string", i("not so long test string"))
        self.assertEqual("Start", i("Start"))
        self.assertEqual("Die Sitzung ist abgelaufen.", i("Session expired."))
