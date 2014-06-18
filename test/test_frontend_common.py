#!/usr/bin/env python3

import unittest
import random
import string
import datetime
import pytz
from cdedb.frontend.common import encode_parameter, decode_parameter, \
     date_filter, datetime_filter

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
            self.assertEqual(decoded, param)
        salt = "a salt"
        target = "some target"
        name = "fancy name"
        param = "an arbitrary message"
        encoded = encode_parameter(salt, target, name, param)
        self.assertEqual(decode_parameter(salt, target, name, encoded,
                                          datetime.timedelta(seconds=0)), None)
        self.assertEqual(decode_parameter("wrong", target, name, encoded,
                                          timeout), None)
        self.assertEqual(decode_parameter(salt, "wrong", name, encoded,
                                          timeout), None)
        self.assertEqual(decode_parameter(salt, target, "wrong", encoded,
                                          timeout), None)
        wrong_encoded = "G" + encoded[1:]
        self.assertEqual(decode_parameter(salt, target, name, wrong_encoded,
                                          timeout), None)

    def test_date_filters(self):
        dt_naive = datetime.datetime(2010, 5, 22, 4, 55)
        dt_aware = datetime.datetime(2010, 5, 22, 4, 55, tzinfo=pytz.utc)
        dt_other = pytz.timezone('America/New_York').localize(dt_naive)
        self.assertEqual(date_filter(dt_naive), "2010-05-22")
        self.assertEqual(date_filter(dt_aware), "2010-05-22")
        self.assertEqual(datetime_filter(dt_naive), "2010-05-22 04:55 ()")
        self.assertEqual(datetime_filter(dt_aware), "2010-05-22 06:55 (CEST)")
        self.assertEqual(datetime_filter(dt_other), "2010-05-22 10:55 (CEST)")
