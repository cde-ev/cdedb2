#!/usr/bin/env python3

import unittest
from unittest.loader import _FailedTest
import sys

if __name__ == "__main__":
    name = None
    filename = None
    if len(sys.argv) > 1 and sys.argv[1].startswith('test_'):
        name = sys.argv[1]
    if len(sys.argv) > 2:
        filename = sys.argv[2]
        filename = filename.split('.')[0]
    if name is None:
        print("No test name provided")
        sys.exit()
    loader = unittest.TestLoader()
    # The TestLoader provides a TestSuite containing a TestSuite per test-file.
    all_tests = loader.discover('./test/', pattern="test_*.py")
    singular_tests = []
    for test_file in all_tests:
        # This test-file contains a TestSuite for each top-level subclass of
        # unittest.TestCase, or a single _FailedTest instance in case of an
        # import error.
        for test_class in test_file:
            if isinstance(test_class, _FailedTest):
                print("Failed to import tests from {}.py".format(
                    str(test_class).split()[0]))
                continue
            # If the import did not fail, this TestSuite cantains all the actual
            # test methods of the test classes in this file.
            for test_case in test_class:
                singular_tests.append(test_case)
    target = []
    for test in singular_tests:
        parts = str(test).split()
        if parts[0] == name:
            if filename is None or filename in str(test):
                target.append(test)
    if target is None:
        print("No test found!")
        sys.exit()
    suite = unittest.TestSuite()
    suite.addTests(target)
    unittest.installHandler()
    testRunner = unittest.runner.TextTestRunner(verbosity=2)
    testRunner.run(suite)
