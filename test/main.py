#!/usr/bin/env python3

import unittest
import sys
from test.common import MyTextTestResult

if __name__ == "__main__":
    loader = unittest.TestLoader()
    unittest.installHandler()
    testRunner = unittest.runner.TextTestRunner(
        verbosity=2, resultclass=MyTextTestResult)
    suite = unittest.TestSuite()
    for arg in sys.argv[1:]:
        suite.addTests(loader.discover('./test/', pattern='*{}*.py'.format(arg)))
    testRunner.run(suite)
