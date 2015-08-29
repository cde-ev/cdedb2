#!/usr/bin/env python3

import unittest
import random
import string
import datetime
import pytz
from cdedb.frontend.common import (
    encode_parameter, decode_parameter, date_filter, datetime_filter,
    cdedbid_filter)

def rand_str(chars, exclude=''):
    pool = string.printable
    pool = "".join(c for c in pool if c not in exclude)
    return "".join(random.choice(pool) for _ in range(chars))

class TestFrontendCommon(unittest.TestCase):
    def test_parameter_encoding(self):
        rounds = 100
        timeout = datetime.timedelta(seconds=300)
        for _ in range(rounds):
            salt = rand_str(12, exclude='-')
            target = rand_str(12, exclude='-')
            name = rand_str(12, exclude='-')
            param = rand_str(200, exclude='-')
            encoded = encode_parameter(salt, target, name, param)
            decoded = decode_parameter(salt, target, name, encoded, timeout)
            self.assertEqual(param, decoded)
        salt = "a salt"
        target = "some target"
        name = "fancy name"
        param = "an arbitrary message"
        encoded = encode_parameter(salt, target, name, param)
        self.assertEqual(None, decode_parameter(salt, target, name, encoded,
                                                datetime.timedelta(seconds=0)))
        self.assertEqual(None, decode_parameter("wrong", target, name, encoded,
                                                timeout))
        self.assertEqual(None, decode_parameter(salt, "wrong", name, encoded,
                                                timeout))
        self.assertEqual(None, decode_parameter(salt, target, "wrong", encoded,
                                                timeout))
        wrong_encoded = "G" + encoded[1:]
        self.assertEqual(None, decode_parameter(salt, target, name, wrong_encoded,
                                                timeout))

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
        self.assertEqual("DB-1-J", cdedbid_filter(1))
        self.assertEqual("DB-2-H", cdedbid_filter(2))
        self.assertEqual("DB-3-F", cdedbid_filter(3))
        self.assertEqual("DB-4-D", cdedbid_filter(4))
        self.assertEqual("DB-5-B", cdedbid_filter(5))
        self.assertEqual("DB-6-K", cdedbid_filter(6))
        self.assertEqual("DB-7-I", cdedbid_filter(7))
        self.assertEqual("DB-8-G", cdedbid_filter(8))
        self.assertEqual("DB-9-E", cdedbid_filter(9))
        self.assertEqual("DB-10-I", cdedbid_filter(10))
        self.assertEqual("DB-11-G", cdedbid_filter(11))
        self.assertEqual("DB-12-E", cdedbid_filter(12))
        self.assertEqual("DB-123-G", cdedbid_filter(123))
        self.assertEqual("DB-11111-C", cdedbid_filter(11111))
        self.assertEqual("DB-11118-K", cdedbid_filter(11118))
