#!/usr/bin/env python3

import unittest
import subprocess


class TestVerificationScript(unittest.TestCase):
    def test_script(self):
        output = subprocess.check_output([
            "bin/verify_vote.py", "snthdiueoa",
            "test/ancillary_files/ballot_result.json"])
        expectation = b"""Versammlung: Internationaler Kongress
Abstimmung: Antwort auf die letzte aller Fragen
Optionen: Ich (1), 23 (2), 42 (3), Philosophie (4)
Eigene Stimme: 3>2=4>_bar_>1
"""
        self.assertEqual(expectation, output)
