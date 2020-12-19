#!/usr/bin/env python3

import unittest
import random
import string
import datetime
import pytz
from cdedb.frontend.common import (
    encode_parameter, decode_parameter, date_filter, datetime_filter,
    cdedbid_filter, tex_escape_filter)

def rand_str(chars, exclude=''):
    pool = string.printable
    pool = "".join(c for c in pool if c not in exclude)
    return "".join(random.choice(pool) for _ in range(chars))

class TestFrontendCommon(unittest.TestCase):
    def test_parameter_encoding(self):
        rounds = 100
        for _ in range(rounds):
            salt = rand_str(12, exclude='-')
            target = rand_str(12, exclude='-')
            name = rand_str(12, exclude='-')
            param = rand_str(200, exclude='-')
            persona_id = random.randint(1, 10000)
            encoded = encode_parameter(salt, target, name, param, persona_id)
            timeout, decoded = decode_parameter(salt, target, name, encoded,
                                                persona_id)
            self.assertEqual(param, decoded)
        salt = "a salt"
        target = "some target"
        name = "fancy name"
        param = "an arbitrary message"
        persona_id = 42
        encoded = encode_parameter(salt, target, name, param, persona_id,
                                   timeout=datetime.timedelta(seconds=-1))
        self.assertEqual(
            (True, None),
            decode_parameter(salt, target, name, encoded, persona_id))

        encoded = encode_parameter(salt, target, name, param, persona_id)
        self.assertEqual(
            (False, None),
            decode_parameter("wrong", target, name, encoded, persona_id))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, "wrong", name, encoded, persona_id))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, target, "wrong", encoded, persona_id))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, target, name, encoded, -1))
        wrong_encoded = "G" + encoded[1:]
        self.assertEqual(
            (False, None),
            decode_parameter(salt, target, name, wrong_encoded, persona_id))

        encoded = encode_parameter(salt, target, name, param, persona_id=None,
                                   timeout=datetime.timedelta(hours=12))
        self.assertEqual(
            (None, param),
            decode_parameter(salt, target, name, encoded, None))
        self.assertEqual(
            (None, param),
            decode_parameter(salt, target, name, encoded, persona_id))
        self.assertEqual(
            (False, None),
            decode_parameter("wrong", target, name, encoded, None))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, "wrong", name, encoded, None))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, target, "wrong", encoded, None))
        self.assertEqual(
            (False, None),
            decode_parameter(salt, target, name, wrong_encoded, None))


    def test_date_filters(self):
        dt_naive = datetime.datetime(2010, 5, 22, 4, 55)
        dt_aware = datetime.datetime(2010, 5, 22, 4, 55, tzinfo=pytz.utc)
        dt_other = pytz.timezone('America/New_York').localize(dt_naive)
        self.assertEqual("2010-05-22", date_filter(dt_naive))
        self.assertEqual("2010-05-22", date_filter(dt_aware))
        self.assertEqual("2010-05-22 04:55 ()", datetime_filter(dt_naive))
        self.assertEqual("2010-05-22 06:55 (CEST)", datetime_filter(dt_aware))
        self.assertEqual("2010-05-22 10:55 (CEST)", datetime_filter(dt_other))

    def test_cdedbid_filter(self):
        self.assertEqual("DB-1-9", cdedbid_filter(1))
        self.assertEqual("DB-2-7", cdedbid_filter(2))
        self.assertEqual("DB-3-5", cdedbid_filter(3))
        self.assertEqual("DB-4-3", cdedbid_filter(4))
        self.assertEqual("DB-5-1", cdedbid_filter(5))
        self.assertEqual("DB-6-X", cdedbid_filter(6))
        self.assertEqual("DB-7-8", cdedbid_filter(7))
        self.assertEqual("DB-8-6", cdedbid_filter(8))
        self.assertEqual("DB-9-4", cdedbid_filter(9))
        self.assertEqual("DB-10-8", cdedbid_filter(10))
        self.assertEqual("DB-11-6", cdedbid_filter(11))
        self.assertEqual("DB-12-4", cdedbid_filter(12))
        self.assertEqual("DB-123-6", cdedbid_filter(123))
        self.assertEqual("DB-11111-2", cdedbid_filter(11111))
        self.assertEqual("DB-11118-X", cdedbid_filter(11118))

    def test_tex_escape_filter(self):
        self.assertEqual(r"\textbackslash foo", tex_escape_filter(r"\foo"))
        self.assertEqual(r"line\textbackslash \textbackslash next",
                         tex_escape_filter(r"line\\next"))
        self.assertEqual(r"a\~{}b", tex_escape_filter(r"a~b"))
        self.assertEqual(r"a\^{}b", tex_escape_filter(r"a^b"))
        self.assertEqual(r"a\{b", tex_escape_filter(r"a{b"))
        self.assertEqual(r"a\}b", tex_escape_filter(r"a}b"))
        self.assertEqual(r"a\_b", tex_escape_filter(r"a_b"))
        self.assertEqual(r"a\#b", tex_escape_filter(r"a#b"))
        self.assertEqual(r"a\%b", tex_escape_filter(r"a%b"))
        self.assertEqual(r"a\&b", tex_escape_filter(r"a&b"))
        self.assertEqual(r"a\$b", tex_escape_filter(r"a$b"))
        self.assertEqual(r"a''b", tex_escape_filter(r'a"b'))
