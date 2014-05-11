#!/usr/bin/env python3

import unittest
import subprocess
import sys

if __name__ == "__main__":
    pattern = 'test*.py'
    exact_test = None
    if len(sys.argv) > 1 and sys.argv[1].endswith('.py'):
        pattern = sys.argv[1]
    loader = unittest.TestLoader()
    tests = loader.discover('./test/', pattern=pattern)
    testRunner = unittest.runner.TextTestRunner(verbosity=2)
    testRunner.run(tests)
