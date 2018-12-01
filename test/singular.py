#!/usr/bin/env python3

import unittest
import sys

if __name__ == "__main__":
    name = None
    filename = None
    exact_test = None
    if len(sys.argv) > 1 and sys.argv[1].startswith('test_'):
        name = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2].startswith('test_'):
        filename = sys.argv[2]
        filename = filename.split('.')[0]
    if name is None:
        print("No test name provided")
        sys.exit()
    loader = unittest.TestLoader()
    all_tests = loader.discover('./test/', pattern="test_*.py")
    # Don't ask about the unpacking below ...
    singular_tests = tuple(c for a in all_tests for b in a for c in b)
    target = None
    for test in singular_tests:
        parts = str(test).split()
        if parts[0] == name:
            if filename is None or filename in str(test):
                if target is not None:
                    print("Non-unique test name!")
                if target is None:
                    target = test
    if target is None:
        print("No test found!")
        sys.exit()
    suite = unittest.TestSuite()
    suite.addTest(target)
    testRunner = unittest.runner.TextTestRunner(verbosity=2)
    testRunner.run(suite)
