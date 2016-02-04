#!/usr/bin/env python3

import unittest
from cdedb.common import (
    extract_roles, schulze_evaluate, int_to_words)
import cdedb.database.constants as const
import datetime
import pytz
import random
import timeit

class TestCommon(unittest.TestCase):
    def test_extract_roles(self):
        self.assertEqual({
            "anonymous", "persona", "cde", "member", "searchable",
            "ml", "assembly", "event",},
            extract_roles({
                'is_active': True,
                'is_cde_realm': True,
                'is_event_realm': True,
                'is_ml_realm': True,
                'is_assembly_realm': True,
                'is_member': True,
                'is_searchable': True,
                }))

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

    def test_number_to_words(self):
        cases = {
            0: "null",
            1: "ein",
            10: "zehn",
            11: "elf",
            12: "zwölf",
            16: "sechzehn",
            28: "achtundzwanzig",
            33: "dreiunddreißig",
            65: "fünfundsechzig",
            77: "siebenundsiebzig",
            99: "neunundneunzig",
            100: "einhundert",
            201: "zweihundertein",
            310: "dreihundertzehn",
            411: "vierhundertelf",
            512: "fünfhundertzwölf",
            616: "sechshundertsechzehn",
            728: "siebenhundertachtundzwanzig",
            833: "achthundertdreiunddreißig",
            965: "neunhundertfünfundsechzig",
            577: "fünfhundertsiebenundsiebzig",
            199: "einhundertneunundneunzig",
            1000: "eintausend",
            2001: "zweitausendein",
            3010: "dreitausendzehn",
            4011: "viertausendelf",
            5012: "fünftausendzwölf",
            6016: "sechstausendsechzehn",
            7028: "siebentausendachtundzwanzig",
            8033: "achttausenddreiunddreißig",
            9065: "neuntausendfünfundsechzig",
            1077: "eintausendsiebenundsiebzig",
            2099: "zweitausendneunundneunzig",
            3100: "dreitausendeinhundert",
            4201: "viertausendzweihundertein",
            5310: "fünftausenddreihundertzehn",
            6411: "sechstausendvierhundertelf",
            7512: "siebentausendfünfhundertzwölf",
            8616: "achttausendsechshundertsechzehn",
            9728: "neuntausendsiebenhundertachtundzwanzig",
            10833: "zehntausendachthundertdreiunddreißig",
            42965: "zweiundvierzigtausendneunhundertfünfundsechzig",
            76577: "sechsundsiebzigtausendfünfhundertsiebenundsiebzig",
            835199: "achthundertfünfunddreißigtausendeinhundertneunundneunzig",
        }
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(cases[case], int_to_words(case, "de"))
