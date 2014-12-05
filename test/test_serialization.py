#!/usr/bin/env python3

import unittest
import datetime
import pytz
import decimal
import serpent
from cdedb.serialization import SERIALIZERS, deserialize
from cdedb.common import EPSILON

for clazz in SERIALIZERS:
    serpent.register_class(clazz, SERIALIZERS[clazz])

class TestSerialization(unittest.TestCase):
    def test_invariance(self):
        corpus = (datetime.datetime.now().date(),
                  datetime.datetime.now(),
                  datetime.datetime.now(pytz.utc),
                  pytz.timezone("America/New_York").localize(
                      datetime.datetime.now()),
                  datetime.datetime.now().time(),
                  1234567890,
                  0,
                  decimal.Decimal("42.188"),
                  decimal.Decimal("42"),
                  decimal.Decimal(".3838848"),
                  None,
                  (datetime.datetime.now(), 123123, "some string"),
                  { "route": 66,
                    None: decimal.Decimal("42.188"),
                    666: datetime.datetime.now(),
                    (1, "tuple"): { 42: datetime.datetime.now()},
                  },
                  )
        for datum in corpus:
            with self.subTest(datum=datum):
                serialized = serpent.dumps(datum)
                deserialized = deserialize(serpent.loads(serialized))
                self.assertEqual(datum, deserialized)
        floats = (.23, 12.0, 1234.34)
        for afloat in floats:
            with self.subTest(afloat=afloat):
                deserialized = deserialize(serpent.loads(serpent.dumps(afloat)))
                self.assertIsInstance(deserialized, float)
                self.assertGreater(EPSILON, abs(afloat - deserialized))
