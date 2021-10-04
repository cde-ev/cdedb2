#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import datetime
import pathlib
import random
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

import pytz

import cdedb.database.constants as const
import cdedb.ml_type_aux as ml_type
from cdedb.common import (
    NearlyNow, extract_roles, int_to_words, mixed_existence_sorter, nearly_now, now,
    schulze_evaluate, unwrap, xsorted, inverse_diacritic_patterns,
)
from cdedb.enums import ALL_ENUMS
from tests.common import ANONYMOUS, BasicTest


class TestCommon(BasicTest):
    def test_mixed_existence_sorter(self) -> None:
        unsorted = [3, 8, -3, 5, 0, -4]
        self.assertEqual(list(mixed_existence_sorter(unsorted)),
                         [0, 3, 5, 8, -3, -4])
        self.assertEqual(sorted([-3, -4]), xsorted([-3, -4]))  # pylint: disable=bad-builtin

    def test_extract_roles(self) -> None:
        self.assertEqual({
            "anonymous", "persona", "cde", "member", "searchable",
            "ml", "assembly", "event", },
            extract_roles({
                'is_active': True,
                'is_cde_realm': True,
                'is_event_realm': True,
                'is_ml_realm': True,
                'is_assembly_realm': True,
                'is_member': True,
                'is_searchable': True,
                }))

    def test_schulze_ordinary(self) -> None:
        bar = '0'  # pylint: disable=blacklisted-name

        def _ordinary_votes(spec: Dict[Optional[Tuple[str, ...]], int],
                            candidates: Tuple[str, ...]) -> List[str]:
            votes = []
            for winners, number in spec.items():
                if winners is None:
                    # abstention
                    vote = '='.join(candidates + (bar,))
                elif not winners:
                    vote = bar + '>' + '='.join(candidates)
                else:
                    vote = '='.join(winners) + '>' + bar + '>' + '='.join(
                        c for c in candidates if c not in winners)
                votes += [vote] * number
            return votes
        candidates = (bar, '1', '2', '3', '4', '5')
        tests: Tuple[Tuple[str, Dict[Optional[Tuple[str, ...]], int]], ...] = (
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
                condensed, detailed = schulze_evaluate(
                    _ordinary_votes(spec, candidates), candidates)
                self.assertEqual(expectation, condensed)

    def test_schulze(self) -> None:
        candidates = ('0', '1', '2', '3', '4')
        # this base set is designed to have a nearly homogeneous
        # distribution (meaning all things are preferred by at most one
        # vote)
        base = ("0>1>2>3>4",
                "4>3>2>1>0",
                "4=0>1=3>2",
                "3>0>2=4>1",
                "1>2=3>4=0",
                "2>1>4>0>3")
        # the advanced set causes an even more perfect equilibrium
        advanced = ("4>2>3>1=0",
                    "0>1=3>2=4",
                    "1=2>0=3=4",
                    "0=3=4>1=2")
        tests: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
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
                condensed, detailed = schulze_evaluate(base+addons, candidates)
                self.assertEqual(expectation, condensed)

    def test_schulze_runtime(self) -> None:
        # silly test, since I just realized, that the algorithm runtime is
        # linear in the number of votes, but a bit more scary in the number
        # of candidates
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

    def test_number_to_words(self) -> None:
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

    def test_collation(self) -> None:
        # Test correct plain string sorting
        names = [
            "",
            " ",
            "16",
            "Stránd",
            "Strassé",
            "straßenpanther",
            "Straßenpanther",
            "Strassenpeter",
            "Zimmer -30",
            "Zimmer -40",
            "Zimmer 20 Das beste Zimmer",
            "Zimmer 100a",
            "Zimmer w20a",
            "Zimmer w100a",
        ]
        shuffled_names = random.sample(names, len(names))
        self.assertEqual(names, xsorted(shuffled_names))

        # Test correct sorting of complex objects with sortkeys
        # Also tests that negative ints are not sorted lexicographically
        dicts = [
            {
                'id': 2,
                'string': 'Erster String',
                'neg': -3,
            },
            {
                'id': 1,
                'string': 'Weiterer String',
                'neg': -2,
            },
            {
                'id': 0,
                'string': 'Z-String',
                'neg': -1,
            }
        ]
        shuffled_dicts = random.sample(dicts, len(dicts))
        self.assertEqual(
            dicts, xsorted(shuffled_dicts, key=lambda x: x['string']))
        self.assertEqual(
            dicts, xsorted(shuffled_dicts, key=lambda x: x['id'], reverse=True))
        self.assertEqual(
            dicts, xsorted(shuffled_dicts, key=lambda x: x['neg'], reverse=False))
        self.assertEqual(
            dicts, xsorted(shuffled_dicts, key=lambda x: str(x['neg']), reverse=True))

        # Test correct sorting of tuples, which would be sorted differently as string
        tuples = [
            ("Corona ", 2020),
            ("Corona", 2020),
        ]
        self.assertEqual(list(reversed(tuples)), xsorted(tuples))
        self.assertEqual(tuples, xsorted(tuples, key=str))

    def test_unwrap(self) -> None:
        self.assertIsInstance(unwrap([1]), int)
        self.assertIsInstance(unwrap((1.0,)), float)
        self.assertIsInstance(unwrap({"a"}), str)
        self.assertIsInstance(unwrap({1: [1.0, "a"]}), list)
        self.assertIsInstance(unwrap({1: [1.0, "a"]}.keys()), int)
        self.assertIsInstance(unwrap({1: {"a": 1.0}}), dict)
        self.assertIsInstance(unwrap(unwrap({1: {"a": 1.0}})), float)

        for item in ("a", b"b"):
            assert isinstance(item, (str, bytes))
            with self.assertRaises(TypeError) as cmt:
                unwrap(item)
            self.assertIn("Cannot unwrap str or bytes.", cmt.exception.args[0])
        for col in ([1, 1.0], (1, "a"), {1.0, "a"}, {1: 1.0, "a": b"b"}):
            with self.assertRaises(ValueError) as cmv:
                unwrap(col)
            self.assertIn("Can only unwrap collections with one element.",
                          cmv.exception.args[0])
        for ncol in (1, 1.0, (i for i in range(1))):
            with self.subTest(ncol=ncol):
                with self.assertRaises(TypeError) as cmt:
                    unwrap(ncol)  # type: ignore
                self.assertIn("Can only unwrap collections.", cmt.exception.args[0])

    def test_untranslated_strings(self) -> None:
        i18n_path = self.conf["REPOSITORY_PATH"] / 'i18n'
        with tempfile.TemporaryDirectory() as tempdir:
            tmppath = pathlib.Path(tempdir, 'i18n')
            shutil.copytree(i18n_path, tmppath)
            subprocess.run(["make", f"I18NDIR={tmppath}", "i18n-refresh"],
                           check=True, capture_output=True)
            try:
                result = subprocess.run(
                    ["make", f"I18NDIR={tmppath}", "i18n-compile"],
                    check=True, capture_output=True, text=True,
                    env={"LC_MESSAGES": "en"}  # makes parsing easier
                )
            except subprocess.CalledProcessError as e:
                self.fail(f"Translation check failed:\n{e.stderr}")

        matches_de = re.search(
            r".*/de/LC_MESSAGES/cdedb.po: \d+ translated messages"
            r"(, (?P<fuzzy>\d+) fuzzy translations?)?"
            r"(, (?P<untranslated>\d+) untranslated messages?)?"
            r"\.",
            result.stderr
        )
        matches_en = re.search(
            r".*/en/LC_MESSAGES/cdedb.po: \d+ translated messages"
            r"(, (?P<fuzzy>\d+) fuzzy translations?)?"
            r", \d+ untranslated messages"
            r"\.",
            result.stderr
        )

        with self.subTest("untranslated"):
            assert matches_de is not None
            self.assertIsNone(matches_de["untranslated"],
                              "There are untranslated strings (de)."
                              " Make sure all strings are translated to German.")
        with self.subTest("fuzzy-de"):
            assert matches_de is not None
            self.assertIsNone(matches_de["fuzzy"],
                              "There are fuzzy translations (de). Double check these"
                              " and remove the '#, fuzzy' marker afterwards.")
        with self.subTest("fuzzy-en"):
            assert matches_en is not None
            self.assertIsNone(matches_en["fuzzy"],
                              "There are fuzzy translations (en). Double check these"
                              " and remove the '#, fuzzy' marker afterwards.")

    def test_ml_type_mismatch(self) -> None:
        pseudo_mailinglist = {"ml_type": const.MailinglistTypes.event_associated}
        bc = ml_type.BackendContainer()
        with self.assertRaises(RuntimeError):
            # Cannot use method of a non-parent-non-child class
            ml_type.AssemblyAssociatedMailinglist.get_implicit_subscribers(
                ANONYMOUS, bc, pseudo_mailinglist)
        with self.assertRaises(RuntimeError):
            # Cannot use method of a child class
            ml_type.AssemblyAssociatedMailinglist.get_implicit_subscribers(
                ANONYMOUS, bc, {"ml_type": const.MailinglistTypes.general_opt_in})
        # Can use method of a parent class
        ml_type.GeneralMailinglist.get_implicit_subscribers(
            ANONYMOUS, bc, pseudo_mailinglist)

    def test_nearly_now(self) -> None:
        base_time = now()
        self.assertEqual(base_time, nearly_now())
        self.assertEqual(base_time + datetime.timedelta(minutes=5), nearly_now())
        self.assertNotEqual(base_time + datetime.timedelta(minutes=15), nearly_now())
        self.assertEqual(base_time + datetime.timedelta(minutes=15),
                         nearly_now(datetime.timedelta(days=1)))
        self.assertNotEqual(base_time + datetime.timedelta(minutes=5),
                            nearly_now(datetime.timedelta(minutes=1)))
        self.assertEqual(NearlyNow.fromisoformat("2012-12-21T12:34:56"),
                         datetime.datetime.fromisoformat("2012-12-21T12:40:00"))

    def test_datetime_min(self) -> None:
        self.assertEqual(datetime.date.min, datetime.date(1, 1, 1))

    def test_inverse_diacritic_patterns(self) -> None:
        pattern = re.compile(inverse_diacritic_patterns("Bertå Böhm"))
        self.assertTrue(pattern.match("Berta Böhm"))
        self.assertTrue(pattern.match("Bertå Boehm"))
        self.assertFalse(pattern.match("Bertä Böhm"))

    def test_enum_str_conversion(self) -> None:
        for enum_ in ALL_ENUMS:
            for member in enum_:
                print(str(member))
                enum_name, member_name = str(member).split('.', 1)
                self.assertEqual(enum_.__name__, enum_name)
                self.assertEqual(member.name, member_name)
                self.assertEqual(member, enum_[member_name])
