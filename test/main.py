#!/usr/bin/env python3

import unittest
import sys
from test.common import MyTextTestResult

if __name__ == "__main__":
    pattern = 'test*.py'
    exact_test = None
    if len(sys.argv) > 1 and sys.argv[1].endswith('.py'):
        pattern = sys.argv[1]
    loader = unittest.TestLoader()
    tests = loader.discover('./test/', pattern=pattern)
    unittest.installHandler()
    testRunner = unittest.runner.TextTestRunner(verbosity=2, resultclass=MyTextTestResult)
    testRunner.run(tests)
