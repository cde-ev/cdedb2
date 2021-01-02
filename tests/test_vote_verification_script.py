#!/usr/bin/env python3

import subprocess
import unittest


class TestVerificationScript(unittest.TestCase):
    def test_verify_vote(self):
        output = subprocess.check_output([
            "bin/verify_vote.py", "snthdiueoa",
            "tests/ancillary_files/ballot_result.json"])
        expectation = b"""Versammlung: Internationaler Kongress
Abstimmung: Antwort auf die letzte aller Fragen
Optionen: Ich (1), 23 (2), 42 (3), Philosophie (4)
Eigene Stimme: 3>2=4>_bar_>1
"""
        self.assertEqual(expectation, output)

    def test_verify_result(self):
        output = subprocess.check_output(
            ["bin/verify_result.py", "tests/ancillary_files/ballot_result.json"],
        )
        expectation = b"""Versammlung: Internationaler Kongress
Abstimmung: Antwort auf die letzte aller Fragen
Optionen: Ich (1)
          23 (2)
          42 (3)
          Philosophie (4)
Detail: Optionen ['3'] bekamen mehr Stimmen als ['2', '4'] mit 2 Pro und 1 Contra Stimmen.
        Optionen ['2', '4'] bekamen mehr Stimmen als ['_bar_'] mit 3 Pro und 1 Contra Stimmen.
        Optionen ['_bar_'] bekamen mehr Stimmen als ['1'] mit 3 Pro und 1 Contra Stimmen.
Ergebnis: 3>2=4>_bar_>1
\xc3\x9cbereinstimmung: ja
"""
        self.assertEqual(expectation, output)
