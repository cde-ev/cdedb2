#!/usr/bin/env python3

import unittest
from cdedb.common import extract_realm, extract_roles, schulze_evaluate
import cdedb.database.constants as const
import datetime
import pytz
import random
import timeit

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

    def test_schulze_ordinary(self):
        bar = '0'
        def _ordinary_votes(spec, candidates):
            votes = []
            for winners, number in spec.items():
                if winners is None:
                    ## abstention
                    vote = '='.join(candidates + (bar,))
                elif not winners:
                    vote = bar + '>' + '='.join(candidates)
                else:
                    vote = '='.join(winners) + '>' + bar + '>' + '='.join(
                        c for c in candidates if c not in winners)
                votes += [vote] * number
            return votes
        candidates = (bar, '1', '2', '3', '4', '5')
        tests = (
            ("0=1>2>3>4=5", {('1',): 3, ('2',): 2, ('3',): 1, ('4',): 0,
                             ('5',): 0, tuple(): 0, None: 0}),
            ("0>1>5>3>4>2", {('1',): 9, ('2',): 0, ('3',): 2, ('4',): 1,
                             ('5',): 8, tuple(): 1, None: 5}),
            ("0>1>2=5>3=4", {('1',): 9, ('2',): 8, ('3',): 2, ('4',): 2,
                             ('5',): 8, tuple(): 5, None: 5}),
            ("1=2=3>0>4=5", {('1', '2', '3'): 2, ('1', '2',): 3, ('3',): 3,
                             ('1', '3'): 1, ('2',): 1}),
        )
        for expectation, spec in tests:
            with self.subTest(spec=spec):
                self.assertEqual(expectation,
                                 schulze_evaluate(_ordinary_votes(
                                     spec, candidates), candidates))

    def test_schulze(self):
        candidates = ('0', '1', '2', '3', '4')
        ## this base set is designed to have a nearly homogeneous
        ## distribution (meaning all things are preferred by at most one
        ## vote)
        base = ("0>1>2>3>4",
                "4>3>2>1>0",
                "4=0>1=3>2",
                "3>0>2=4>1",
                "1>2=3>4=0",
                "2>1>4>0>3")
        ## the advanced set causes an even more perfect equilibrium
        advanced = ("4>2>3>1=0",
                    "0>1=3>2=4",
                    "1=2>0=3=4",
                    "0=3=4>1=2")
        tests = (
            ("0=1>3>2>4", tuple()),
            ("2=4>3>0>1", ("4>2>3>0>1",)),
            ("2=4>1=3>0", ("4>2>3>1=0",)),
            ("0=3=4>1=2", ("4>2>3>1=0", "0>1=3>2=4")),
            ("1=2>0=3=4", ("4>2>3>1=0", "0>1=3>2=4", "1=2>0=3=4")),
            ("0=3=4>1=2", ("4>2>3>1=0", "0>1=3>2=4", "1=2>0=3=4", "0=3=4>1=2")),
            ("0=3=4>1=2", advanced),
            ("0>1=3=4>2", advanced + ("0>1=2=3=4",)),
            ("0=1>3=4>2", advanced + ("1>0=2=3=4",)),
            ("2=3>0=4>1", advanced + ("2>0=1=3=4",)),
            ("3>0=2=4>1", advanced + ("3>0=1=2=4",)),
            ("4>0=3>1=2", advanced + ("4>0=1=2=3",)),
            ("0>3>1=4>2", advanced + ("0>3>4=1>2",)),
            ("0>3>4>1>2", advanced + ("0>3>4>1>2",)),
            ("2>1>4>3>0", advanced + ("2>1>4>3>0",)),
            ("4>3>2>0=1", advanced + ("4>3>2>1>0",)),
            ("0>1>2=3>4", advanced + ("0>1>2>3>4",)),
            ("0=3>1=2>4", advanced + ("0=1=2=3>4",)),
            ("0=2=4>1>3", advanced + ("0=1=2=4>3",)),
            ("0=3=4>1>2", advanced + ("0=1=3=4>2",)),
            ("0=3=4>2>1", advanced + ("0=2=3=4>1",)),
            ("1=3=4>2>0", advanced + ("1=2=3=4>0",)),
        )
        for expectation, addons in tests:
            with self.subTest(addons=addons):
                self.assertEqual(expectation,
                                 schulze_evaluate(base+addons, candidates))

    def test_schulze_runtime(self):
        ## silly test, since I just realized, that the algorithm runtime is
        ## linear in the number of votes, but a bit more scary in the number
        ## of candidates
        candidates = ('0', '1', '2', '3', '4')
        votes = []
        for _ in range(2000):
            parts = list(candidates)
            random.shuffle(parts)
            relations = (random.choice(('=', '>'))
                         for _ in range(len(candidates)))
            vote = ''.join(c + r for c, r in zip(candidates, relations))
            votes.append(vote[:-1])
        times = {}
        for num in (10, 100, 1000, 2000):
            start = datetime.datetime.now(pytz.utc)
            for _ in range(10):
                schulze_evaluate(votes[:num], candidates)
            stop = datetime.datetime.now(pytz.utc)
            times[num] = stop - start
        reference = datetime.timedelta(milliseconds=5)
        for num, delta in times.items():
            self.assertGreater(num*reference, delta)
