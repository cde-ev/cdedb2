#! /usr/bin/env python3
"""Calling this script is the canonical way to run the test suite."""

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

from bin.check_utils import MyTextTestResult, MyTextTestRunner
from bin.escape_fuzzing import work as xss_check

import tests.backend_tests as backend_tests
import tests.frontend_tests as frontend_tests
import tests.ldap_tests as ldap_tests
import tests.other_tests as other_tests
from cdedb.config import TestConfig


class CdEDBTestLock:
    """
    Simple lock mechanism to prevent multiple tests accessing the same
    test database and files simultaneously.
    """
    # Identifiers of existing test threads. Only truthy values allowed, and a
    # corresponding config file in tests/config/ must exist.
    # Use the returned configpath to prepare the test environment properly.

    # interchangeable threads to run application tests, are acquired by default
    APPLICATION_THREADS = ("1", "2", "3", "4")
    # special threads to run the ldap or xss tests, must be acquired directly
    SPECIAL_THREADS = ("ldap", "xss")
    ALL_THREADS = tuple(thread for thread in [*APPLICATION_THREADS, *SPECIAL_THREADS])

    thread: Optional[str]
    lockfile: TextIO

    def __init__(self, thread: str = None):
        if not ((thread is None) or (thread in self.ALL_THREADS)):
            raise RuntimeError("Invalid thread name.")
        self.thread = thread

    @property
    def lockfile_path(self) -> pathlib.Path:
        return pathlib.Path('/tmp') / f'cdedb-test-{self.thread}.lock'

    @property
    def configpath(self) -> pathlib.Path:
        return root / f"tests/config/test_{self.thread}.py"

    def acquire(self) -> None:
        """Lock the thread"""
        if self.thread is not None:
            try:
                self.lockfile = open(self.lockfile_path, 'x')
                return
            except FileExistsError:
                raise RuntimeError(f"Thread {self.thread} is currently in use.")
        else:
            # as promised, only choose one of the application test threads automatically
            for thread in self.APPLICATION_THREADS:
                try:
                    self.thread = thread
                    self.lockfile = open(self.lockfile_path, 'x')
                    return
                except FileExistsError:
                    continue
            self.thread = None
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


def run_application_tests(configpath: pathlib.Path, testpatterns: List[str] = None, *,
                          verbose: bool = False) -> int:
    conf = TestConfig(configpath)
    # get the user running the current process, so the access rights for log directory
    # are set correctly
    user = getpass.getuser()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)
    # create the log directory
    subprocess.run(["make", "log", f"LOG_DIR={conf['LOG_DIR']}", f"DATA_USER={user}"],
                   check=True, stdout=subprocess.DEVNULL)
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


def run_xss_tests(configpath: pathlib.Path, *, verbose: bool = False) -> int:
    conf = TestConfig(configpath)
    # get the user running the current process, so the access rights for log directory
    # are set correctly
    user = getpass.getuser()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)
    # create the log directory
    subprocess.run(["make", "log", f"LOG_DIR={conf['LOG_DIR']}", f"DATA_USER={user}"],
                   check=True, stdout=subprocess.DEVNULL)
    # setup the database
    subprocess.run(["make", "sql-xss", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}",
                    f"XSS_PAYLOAD={conf['XSS_PAYLOAD']}"],
                   check=True, stdout=subprocess.DEVNULL)
    # create the storage directory
    subprocess.run(["make", "storage", f"STORAGE_DIR={conf['STORAGE_DIR']}",
                    f"DATA_USER={user}"], check=True, stdout=subprocess.DEVNULL)
    # add the configpath to environment to access the configuration inside the tests
    os.environ['CDEDB_TEST_CONFIGPATH'] = str(configpath)

    ret = xss_check(
        configpath, conf["XSS_OUTDIR"], verbose=verbose, payload=conf["XSS_PAYLOAD"],
        secondary_payload=conf["XSS_PAYLOAD_SECONDARY"]
    )

    return ret


def run_ldap_tests(configpath: pathlib.Path, testpatterns: List[str] = None, *,
                   verbose: bool = False) -> int:
    conf = TestConfig(configpath)
    # get the user running the current process, so the access rights for log directory
    # are set correctly
    user = getpass.getuser()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)
    # create the log directory
    subprocess.run(["make", "log", f"LOG_DIR={conf['LOG_DIR']}", f"DATA_USER={user}"],
                   check=True, stdout=subprocess.DEVNULL)
    if pathlib.Path("/CONTAINER").is_file():
        # the database is already initialized, since it is needed to start the
        # ldap container in the first place
        print(f"Database {conf['CDB_DATABASE_NAME']} must already been set up.")
        # TODO verify this somehow
    else:
        # setup the database
        subprocess.run(["make", "sql", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}"],
                       check=True, stdout=subprocess.DEVNULL)
        # update the current ldap setting
        # TODO either run ldap-reset or only ldap-update-full
        # subprocess.run(["make", "ldap-create"], check=True)
        subprocess.run(
            ["make", "ldap-update-full", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}"],
            check=True, stdout=subprocess.DEVNULL)
    # add the configpath to environment to access the configuration inside the tests
    os.environ['CDEDB_TEST_CONFIGPATH'] = str(configpath)

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
    parser.add_argument('testpatterns', default=[], nargs="*",
                        help="patterns matched against full qualified test name")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="more detailed output")

    presets = parser.add_argument_group(
        "pattern presets for running application tests in parallel")
    presets.add_argument('--first', '-1', action='store_true',
                         help="run first half of the frontend tests"
                              " (everything before event tests)")
    presets.add_argument('--second', '-2', action='store_true',
                         help="run second half of the frontend tests (event"
                              " tests and following)")
    presets.add_argument('--third', '-3', action='store_true',
                         help="run third part of application tests (everything except"
                              " for the frontend tests)")

    parts = parser.add_argument_group(
        "choose which parts of the testsuite to run (application tests are default)")
    parts.add_argument('--ldap', action='store_true',
                       help="run ldap tests")
    parts.add_argument('--xss', action='store_true',
                       help="run xss check")
    parts.add_argument('--no-application', action='store_true',
                       help="do not run application tests")

    pattern_overrides = parser.add_argument_group(
        "override given testpatterns for parts of the testsuite")
    pattern_overrides.add_argument('--all', action='store_true',
                                   help="run _all_ tests regardless of testpatterns")
    pattern_overrides.add_argument('--all-ldap', action='store_true',
                                   help="run all ldap tests regardless of testpatterns")
    pattern_overrides.add_argument('--all-application', action='store_true',
                                   help="run all application tests regardless of"
                                        " testpatterns")

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
        args.all_application = False
        args.no_application = False
        args.all_ldap = False
        args.ldap = False
        args.xss = False

    return_code = 0

    # Always run application tests unless explicitly deactivated.
    do_application = args.all or not args.no_application
    # Only run ldap if specified or all tests are run.
    do_ldap = args.all or args.all_ldap or args.ldap
    # Only run xss check if specified or all tests are run.
    do_xss = args.all or args.xss

    if do_application:
        # Override testpatterns to run all tests.
        if args.all or args.all_application:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        with CdEDBTestLock() as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            return_code += run_application_tests(
                configpath=Lock.configpath, testpatterns=testpatterns,
                verbose=args.verbose)

    if do_ldap:
        # Override testpatterns to run all tests.
        if args.all or args.all_ldap:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        with CdEDBTestLock("ldap") as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            return_code += run_ldap_tests(
                configpath=Lock.configpath, testpatterns=testpatterns,
                verbose=args.verbose)

    if do_xss:
        with CdEDBTestLock("xss") as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            return_code += run_xss_tests(
                configpath=Lock.configpath, verbose=args.verbose)

    sys.exit(return_code)
