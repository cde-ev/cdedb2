#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import subprocess
import unittest


class TestVerificationScript(unittest.TestCase):
    def test_verify_vote(self) -> None:
        output = subprocess.check_output([
            "bin/verify_vote.py", "snthdiueoa",
            "tests/ancillary_files/ballot_result.json"])
        expectation = b"""Versammlung: Internationaler Kongress
Abstimmung: Antwort auf die letzte aller Fragen
Optionen: Ich (1), 23 (2), 42 (3), Philosophie (4)
Eigene Stimme: 3>2=4>_bar_>1
"""
        self.assertEqual(expectation, output)

    def test_verify_result(self) -> None:
        output = subprocess.check_output(
            ["bin/verify_result.pyz", "tests/ancillary_files/ballot_result.json"],
        )
        expectation = b"""Versammlung: Internationaler Kongress
Abstimmung: Antwort auf die letzte aller Fragen
Optionen: Ich (1)
          23 (2)
          42 (3)
          Philosophie (4)
Detail: Optionen ['3'] bekamen mehr Stimmen als ['2', '4']
          mit ('3', '2'): 2, ('3', '4'): 2 Pro
          und ('3', '2'): 1, ('3', '4'): 1 Contra Stimmen.
        Optionen ['2', '4'] bekamen mehr Stimmen als ['_bar_']
          mit ('2', '_bar_'): 3, ('4', '_bar_'): 2 Pro
          und ('2', '_bar_'): 1, ('4', '_bar_'): 2 Contra Stimmen.
        Optionen ['_bar_'] bekamen mehr Stimmen als ['1']
          mit ('_bar_', '1'): 3 Pro
          und ('_bar_', '1'): 1 Contra Stimmen.
Ergebnis: 3>2=4>_bar_>1
\xc3\x9cbereinstimmung: ja
"""
        self.assertEqual(expectation, output)
