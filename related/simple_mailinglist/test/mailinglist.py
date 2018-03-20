#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit-test for simple_mailinglist

:Requires: Python >= 3.x TODO

:Version:   0.2-work-in-progress

:Author:    Roland Koebler <rk@simple-is-better.org>
:Copyright: Roland Koebler
:License:   MIT/X11-like, see __license__

:VCS:       $Id$
"""

import unittest

from simple_mailinglist import *

#unittest.TestCase.assertRaisesMsg = lambda self, exc, msg: self.assertRaisesRegex(exc, re.escape(msg))

#=========================================

class TestHelper(unittest.TestCase):
    """Test helper functions.
    """
    #pylint: disable=protected-access
    def test_json_load_f(self):
        """Test jsondict_load(...).
        """
        # non-existing file
        self.assertEqual(jsondict_load(""), {})
        self.assertRaises(IOError, jsondict_load, "foo")
        # non-regular file
        self.assertRaises(IOError, jsondict_load, ".")
        # permission denied
        self.assertRaises(IOError, jsondict_load, "cfg_nonreadable.json")
        # invalid JSON
        self.assertRaises(ValueError, jsondict_load, "cfg_json_invalid.json")
        # non-dict
        self.assertRaises(ValueError, jsondict_load, "cfg_json_list.json")
        # valid
        self.assertEqual(jsondict_load("cfg_dummy.json"), {})

    def test_json_load_s(self):
        """Test jsondict_load(s=...).
        """
        # invalid JSON
        self.assertRaises(ValueError, jsondict_load, s="invalid")
        # non-dict
        self.assertEqual(jsondict_load(s=""), {})
        self.assertRaises(ValueError, jsondict_load, s="[1, 2, 3]")
        # valid
        self.assertEqual(jsondict_load(s='{"listname": "MyList"}'), {"listname": "MyList"})

    def test_json_load_fs(self):
        """Test jsondict_load(..., s=...).
        """
        self.assertEqual(jsondict_load("cfg_dummy.json", '{"listname": "Ignored"}'), {})

    def test_emailadr_extract(self):
        """Test emailadr_extract(s).
        """
        # lower case
        self.assertEqual(emailadr_extract("foo@example.com"), "foo@example.com")
        # mixed case
        self.assertEqual(emailadr_extract("  FooBar@eXample.cOm "), "foobar@example.com")
        # Name <...>
        self.assertEqual(emailadr_extract("<FooBar@eXample.cOm>"), "foobar@example.com")
        self.assertEqual(emailadr_extract("Mr. Foo <FooBar@eXample.cOm>"), "foobar@example.com")
        self.assertEqual(emailadr_extract("Mr. Foo <FooBar@eXample.cOm> trailing"), "foobar@example.com")
        # too many < / >
        self.assertRaises(ValueError, emailadr_extract, "Mr. X<Y <FooBar@eXample.cOm>")

class TestCfg(unittest.TestCase):
    """Test configuration-files.
    """

    def test_cfg_load(self):
        """Test cfg_load().
        """
        pass
        # non-existing file
        # non-regular file
        # permission denied
        # invalid JSON
        # non-dict
        # ok
        # include 1
        # include 2
        # include recursively
        # include with incompatible values
        # extend_exec + allow_exec=False
        # extend_exec + allow_exec=True

    def test_cfg_extend(self):
        """Test cfg_extend().
        """
        pass
        # extend_exec + allow_exec=True + exec fails
        # extend_exec + allow_exec=True + exec ok + invalid JSON
        # extend_exec + allow_exec=True + exec ok + non-dict
        # extend_exec + allow_exec=True + exec ok + invaild contents
        # extend_exec + allow_exec=True + exec ok + ok

#=========================================
if __name__ == '__main__':
    unittest.main(verbosity=2)

#=========================================
