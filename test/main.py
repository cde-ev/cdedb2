#!/usr/bin/env python3

import sys
import unittest
from test.common import MyTextTestResult, check_test_setup

if __name__ == "__main__":
    check_test_setup()
    loader = unittest.TestLoader()
    unittest.installHandler()
    testRunner = unittest.runner.TextTestRunner(
        verbosity=2, resultclass=MyTextTestResult)
    suite = unittest.TestSuite()
    if any(sys.argv[1:]):
        for arg in sys.argv[1:]:
            suite.addTests(loader.discover('./test/', pattern='*{}*.py'.format(arg)))
    else:
        suite.addTests(loader.discover('./test/', pattern='test*.py'))
    testRunner.run(suite)
