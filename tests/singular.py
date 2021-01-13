#!/usr/bin/env python3

import os
import pathlib
import sys
import unittest

from tests.common import MyTextTestRunner, MyTextTestResult, check_test_setup

# the directory containing the cdedb and tests modules
root = pathlib.Path(__file__).absolute().parent.parent

if __name__ == "__main__":
    check_test_setup()
    os.environ['CDEDB_TEST_SINGULAR'] = "True"

    patterns = sys.argv[1].split()

    unittest.defaultTestLoader.testNamePatterns = [
        pattern if "*" in pattern else f"*{pattern}*" for pattern in patterns]
    all_tests = unittest.defaultTestLoader.discover('./tests/', top_level_dir=root)

    unittest.installHandler()
    testRunner = MyTextTestRunner(verbosity=2, resultclass=MyTextTestResult)
    testRunner.run(all_tests)
