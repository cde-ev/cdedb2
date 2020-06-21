#!/usr/bin/env python3

import os
import unittest
import sys
from test.common import MyTextTestResult

if __name__ == "__main__":
    if not os.environ.get('CDEDB_TEST'):
        raise RuntimeError("Not configured for test (CDEDB_TEST unset).")
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
