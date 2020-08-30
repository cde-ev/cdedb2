#!/usr/bin/env python3

import os
import unittest
import sys
from test.common import MyTextTestResult, check_test_setup

if __name__ == "__main__":
    check_test_setup()
    os.environ['CDEDB_TEST_SINGULAR'] = "True"
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
            if not hasattr(test_class, '__iter__'):
                print("Failed to import tests from {}.py".format(
                    str(test_class).split()[0]))
                continue
            # If the import did not fail, this TestSuite cantains all the actual
            # test methods of the test classes in this file.
            for test_case in test_class:
                singular_tests.append(test_case)
    targets = []
    for test in singular_tests:
        parts = str(test).split()
        if parts[0] == name:
            if filename is None or filename in str(test):
                targets.append(test)
    if not targets:
        print("No test found!")
        sys.exit()
    suite = unittest.TestSuite()
    suite.addTests(targets)
    unittest.installHandler()
    testRunner = unittest.runner.TextTestRunner(
        verbosity=2, resultclass=MyTextTestResult)
    testRunner.run(suite)
