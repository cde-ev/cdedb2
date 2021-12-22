#! /usr/bin/env python3

import argparse
import getpass
import os
import pathlib
import subprocess
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

from bin.escape_fuzzing import work as xss_check

import tests.backend_tests as backend_tests
import tests.frontend_tests as frontend_tests
import tests.ldap_tests as ldap_tests
import tests.other_tests as other_tests
from cdedb.config import TestConfig
from tests.custom_testrunners import MyTextTestResult, MyTextTestRunner


class CdEDBTestLock:
    """
    Simple lock mechanism to prevent multiple tests accessing the same
    test database and files simultaneously.
    """
    # Identifiers of existing test threads. Only truthy values allowed, and a
    # corresponding config file in tests/config/ must exist.
    # Use the returned configpath to prepare the test environment properly.
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
    """Load all tests from test_modules matching one of testpatterns."""
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
    conf = TestConfig(configpath)
    # get the user running the current process, so the access rights for log directory
    # are set correctly
    user = getpass.getuser()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True)
    # create the log directory
    subprocess.run(["make", "log", f"LOG_DIR={conf['_LOG_ROOT']}", f"DATA_USER={user}"],
                   check=True)
    # setup the database
    subprocess.run(["make", "sql", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}"],
                   check=True, stdout=subprocess.DEVNULL)
    # add the configpath to environment to access the configuration inside the tests
    os.environ['CDEDB_TEST_CONFIGPATH'] = str(configpath)

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
    conf = TestConfig(configpath)
    # get the user running the current process, so the access rights for log directory
    # are set correctly
    user = getpass.getuser()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True)
    # create the log directory
    subprocess.run(["make", "log", f"LOG_DIR={conf['_LOG_ROOT']}", f"DATA_USER={user}"],
                   check=True)
    # setup the database
    subprocess.run(["make", "sql-xss", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}",
                    f"XSS_PAYLOAD={conf['XSS_PAYLOAD']}"],
                   check=True, stdout=subprocess.DEVNULL)
    # create the storage directory
    subprocess.run(["make", "storage", f"STORAGE_DIR={conf['STORAGE_DIR']}",
                    f"DATA_USER={user}"], check=True)
    # add the configpath to environment to access the configuration inside the tests
    os.environ['CDEDB_TEST_CONFIGPATH'] = str(configpath)

    ret = xss_check(
        configpath, conf["XSS_OUTDIR"], verbose=verbose, payload=conf["XSS_PAYLOAD"],
        secondary_payload=conf["XSS_PAYLOAD_SECONDARY"]
    )

    return ret


def run_ldap_tests(testpatterns: List[str] = None, *, verbose: bool = False) -> int:
    return 1
    configpath = root / "tests/config/test_ldap.py"  # type: ignore[unreachable]
    prepare_environment(configpath)  # type: ignore[name-defined]

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

    presets = parser.add_argument_group(
        "options for running suite in parallel (all together cover full suite)")
    presets.add_argument('--first', '-1', action='store_true',
                         help="run first half of the frontend tests"
                              " (everything before event tests)")
    presets.add_argument('--second', '-2', action='store_true',
                         help="run second half of the frontend tests (event"
                              " tests and following)")
    presets.add_argument('--third', '-3', action='store_true',
                         help="run third part of test suite (everything except"
                              " for the frontend tests)")

    parts = parser.add_argument_group("choose which parts of the testsuite to run")
    parts.add_argument('--ldap', action='store_true',
                       help="run ldap tests")
    parts.add_argument('--xss', action='store_true',
                       help="run xss check")
    parts.add_argument('--no-unittests', action='store_true',
                       help="do not run unittests")

    pattern_overrides = parser.add_argument_group(
        "override given testpatterns for parts of the testsuite")
    pattern_overrides.add_argument('--all', action='store_true',
                                   help="run _all_ tests regardless of testpatterns")
    pattern_overrides.add_argument('--all-ldap', action='store_true',
                                   help="run all ldap tests regardless of testpatterns")
    pattern_overrides.add_argument('--all-unittests', action='store_true',
                                   help="run all unittests regardless of testpatterns")

    parser.add_argument('--verbose', '-v', action='store_true',
                        help="more detailed output")
    args = parser.parse_args()

    # Set args for presets.
    if args.first:
        args.testpatterns.append('tests.frontend_tests.[abcd]*')
    if args.second:
        args.testpatterns.append('tests.frontend_tests.[!abcd]*')
    if args.third:
        args.testpatterns.append('tests.backend_tests.*')
        args.testpatterns.append('tests.other_tests.*')
    if args.first or args.second or args.third:
        args.all = False
        args.all_unittests = False
        args.no_unittests = False
        args.all_ldap = False
        args.ldap = False
        args.xss = False

    return_code = 0

    # Always run inittest unless explicitly deactivated.
    do_unittests = args.all or not args.no_unittests
    # Only run ldap if specified or all tests are run.
    do_ldap = args.all or args.all_ldap or args.ldap
    # Only run xss check if specified or all tests are run.
    do_xss = args.all or args.xss

    if do_unittests:
        with CdEDBTestLock(None) as Lock:
            assert Lock.thread_id is not None
            print(f"Using thread {Lock.thread_id}", file=sys.stderr)

            # Override testpatterns to run all tests.
            if args.all or args.all_unittests:
                testpatterns = None
            else:
                testpatterns = args.testpatterns

            return_code += run_regular_tests(
                configpath=Lock.configpath, testpatterns=testpatterns,
                verbose=args.verbose)

    if do_ldap:
        # Override testpatterns to run all tests.
        if args.all or args.all_ldap:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        return_code += run_ldap_tests(testpatterns, verbose=args.verbose)

    if do_xss:
        return_code += run_xss_tests(verbose=args.verbose)

    sys.exit(return_code)
