#!/usr/bin/env python3

import os
import pathlib
import sys
import unittest

from tests.common import MyTextTestResult, MyTextTestRunner, check_test_setup

# the directory containing the cdedb and tests modules
root = pathlib.Path(__file__).absolute().parent.parent

if __name__ == "__main__":
    check_test_setup()

    patterns = sys.argv[1].split()

    unittest.defaultTestLoader.testNamePatterns = [
        pattern if "*" in pattern else f"*{pattern}*" for pattern in patterns]
    all_tests = unittest.defaultTestLoader.discover('tests', top_level_dir=str(root))

    unittest.installHandler()
    testRunner = MyTextTestRunner(
        verbosity=1, resultclass=MyTextTestResult, descriptions=False)
    # TODO: differentiate verbosity between auto-parallel run and manual run

    sys.exit(0 if testRunner.run(all_tests).wasSuccessful() else 1)
