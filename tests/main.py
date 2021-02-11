#!/usr/bin/env python3

import sys
import unittest

from tests.common import MyTextTestResult, MyTextTestRunner, check_test_setup

if __name__ == "__main__":
    check_test_setup()
    loader = unittest.TestLoader()
    unittest.installHandler()
    testRunner = MyTextTestRunner(verbosity=2, resultclass=MyTextTestResult)
    suite = unittest.TestSuite()
    if any(sys.argv[1:]):
        for arg in sys.argv[1:]:
            suite.addTests(loader.discover('./tests/', pattern='*{}*.py'.format(arg)))
    else:
        suite.addTests(loader.discover('./tests/', pattern='test*.py'))

    sys.exit(0 if testRunner.run(suite).wasSuccessful() else 1)
