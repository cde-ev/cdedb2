#! /usr/bin/env python3

import argparse
import os
import pathlib
import sys
import unittest
from types import ModuleType, TracebackType
from typing import List, Optional, TextIO, Type
from unittest import TestLoader, TestSuite

# the directory containing the cdedb and tests modules
root = pathlib.Path(__file__).absolute().parent.parent
# add it to sys.path to make this script executable directly from everywhere
sys.path.append(str(root))
# this is necessary for calling make as subprocess
os.chdir(root)

# import helpers to prepare and execute the tests
from bin.escape_fuzzing import work as xss_check
from tests.custom_testrunners import MyTextTestResult, MyTextTestRunner
from tests.prepare_tests import prepare_environment, prepare_storage

# import all TestCases which should be tested
import tests.backend_tests as backend_tests
import tests.frontend_tests as frontend_tests
import tests.ldap_tests as ldap_tests
import tests.other_tests as other_tests


class CdEDBTestLock:
    """
    Simple lock mechanism to prevent multiple tests accessing the same
    test database and files simultaneously.
    """
    # Identifiers of existing test threads. Only truthy values allowed.
    # Take care that the database setup is configured accordingly.
    # TODO: improve this in #1948
    THREADS = (1, 2, 3, 4)

    configpath: pathlib.Path
    thread_id: Optional[int]
    lockfile: TextIO

    def __init__(self, thread_id: Optional[int] = None):
        if not ((thread_id is None) or (thread_id in self.THREADS)):
            raise RuntimeError("Invalid thread id")
        self.thread_id = thread_id

    @property
    def lockfile_path(self) -> pathlib.Path:
        return pathlib.Path('/tmp') / f'cdedb-test-{self.thread_id}.lock'

    def acquire(self) -> None:
        """Lock the thread"""
        if self.thread_id is not None:
            try:
                self.lockfile = open(self.lockfile_path, 'x')
                return
            except FileExistsError:
                raise RuntimeError(f"Thread {self.thread_id} is currently in use.")
        else:
            for thread_id in self.THREADS:
                try:
                    self.thread_id = thread_id
                    self.lockfile = open(self.lockfile_path, 'x')
                    self.configpath = root / f"tests/config/test_{self.thread_id}.py"
                    return
                except FileExistsError:
                    continue
            self.thread_id = None
            raise RuntimeError("All threads are currently in use.")

    def release(self) -> None:
        """Unlock the thread"""
        self.lockfile.close()
        self.lockfile_path.unlink()

    def __enter__(self) -> "CdEDBTestLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> None:
        self.release()


def _load_tests(testpatterns: Optional[List[str]],
                test_modules: List[ModuleType] = None) -> TestSuite:
    """Load all tests from test_modules and test_cases matching one of testpatterns."""
    test_modules = test_modules or list()

    test_loader = TestLoader()
    test_suite = TestSuite()

    # when no/empty pattern given, specify nothing to run all tests given
    if testpatterns:
        test_loader.testNamePatterns = [
            pattern if "*" in pattern else f"*{pattern}*" for pattern in testpatterns
        ]

    for test_module in test_modules:
        test_suite.addTests(test_loader.loadTestsFromModule(test_module))

    return test_suite


def run_regular_tests(configpath: pathlib.Path, testpatterns: List[str] = None, *,
                      verbose: bool = False) -> int:
    prepare_environment(configpath)

    # load all tests which are not meant to be run separately (f.e. the ldap tests)
    test_modules = [backend_tests, frontend_tests, other_tests]
    test_suite = _load_tests(testpatterns, test_modules)

    unittest.installHandler()
    test_runner = MyTextTestRunner(verbosity=(2 if verbose else 1),
                                   resultclass=MyTextTestResult, descriptions=False)
    ran_tests = test_runner.run(test_suite)
    return 0 if ran_tests.wasSuccessful() else 1


def run_xss_tests(*, verbose: bool = False) -> int:
    configpath = root / "tests/config/test_xss.py"
    conf = prepare_environment(configpath, prepare_xss=True)
    prepare_storage(conf)

    ret = xss_check(
        configpath, conf["XSS_OUTDIR"], verbose=verbose, payload=conf["XSS_PAYLOAD"],
        secondary_payload=conf["XSS_PAYLOAD_SECONDARY"]
    )

    return ret


def run_ldap_tests(testpatterns: List[str] = None, *, verbose: bool = False) -> int:
    configpath = root / "tests/config/test_ldap.py"
    prepare_environment(configpath)

    test_suite = _load_tests(testpatterns, [ldap_tests])

    unittest.installHandler()
    test_runner = MyTextTestRunner(verbosity=(2 if verbose else 1),
                                   resultclass=MyTextTestResult, descriptions=False)
    ran_tests = test_runner.run(test_suite)
    return 0 if ran_tests.wasSuccessful() else 1


if __name__ == '__main__':
    # parse arguments
    parser = argparse.ArgumentParser(
        description="Entry point to CdEDB's testing facilities.")
    parser.add_argument('testpatterns', default=[], nargs="*")

    test_options = parser.add_argument_group("general options")
    test_options.add_argument('--manual-preparation', action='store_true',
                              help="don't do test preparation")
    # TODO is this necessary?
    test_options.add_argument(
        '--thread-id', type=int, choices=(1, 2, 3, 4), metavar="INT",
        help="ID of thread to use for run (optional, if not given, choose free thread"
             " automatically)")

    parallel_options = parser.add_argument_group(
        "options for running suite in parallel (all together cover full suite)")
    parallel_options.add_argument('--first', '-1', action='store_true',
                                  help="run first half of the frontend tests"
                                       " (everything before event tests)")
    parallel_options.add_argument('--second', '-2', action='store_true',
                                  help="run second half of the frontend tests (event"
                                       " tests and following)")
    parallel_options.add_argument('--third', '-3', action='store_true',
                                  help="run third part of test suite (everything except"
                                       " for the frontend tests)")
    parallel_options.add_argument('--ldap', action='store_true',
                                  help="also run ldap tests")
    parallel_options.add_argument('--ldap-only', action='store_true',
                                  help="run ldap tests, but not regular tests.")
    parallel_options.add_argument('--xss', action='store_true',
                                  help="also run xss check")
    parallel_options.add_argument('--all', action='store_true',
                                  help="run _all_ tests.")
    parallel_options.add_argument('--all-tests', action='store_true',
                                  help="run all regular tests.")
    parallel_options.add_argument('--all-ldap', action='store_true',
                                  help="run all ldap tests.")

    parser.add_argument('--verbose', '-v', action='store_true',
                        help="more detailed output")
    args = parser.parse_args()

    # Split regular tests into three parts with similar runtime
    if args.first:
        args.testpatterns.append('tests.frontend_tests.[abcd]*')
    if args.second:
        args.testpatterns.append('tests.frontend_tests.[!abcd]*')
    if args.third:
        args.testpatterns.append('tests.backend_tests.*')
        args.testpatterns.append('tests.other_tests.*')

    return_code = 0

    # Run tests in case of `all` or `all_tests` or if
    # `testpatterns` are given and `ldap_only` is not.
    if args.all or args.all_tests or args.testpatterns and not args.ldap_only:
        with CdEDBTestLock(args.thread_id) as Lock:
            assert Lock.thread_id is not None
            print(f"Using thread {Lock.thread_id}", file=sys.stderr)

            # Override testpatterns to run all tests.
            if args.all or args.all_tests:
                testpatterns = None
            else:
                testpatterns = args.testpatterns

            return_code += run_regular_tests(
                configpath=Lock.configpath, testpatterns=testpatterns,
                verbose=args.verbose)

    # Run ldap if `ldap`, `ldap_only`, `all_ldap` or `all` is set.
    if args.ldap or args.ldap_only or args.all_ldap or args.all:
        # Override testpatterns to run all tests.
        if args.all or args.all_ldap:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        return_code += run_ldap_tests(testpatterns, verbose=args.verbose)

    # Run xss if `xss` or `all` is set.
    if args.xss or args.all:
        return_code += run_xss_tests(verbose=args.verbose)

    sys.exit(return_code)
