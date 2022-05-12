#! /usr/bin/env python3
"""Calling this script is the canonical way to run the test suite."""

import argparse
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

from cdedb.cli.database import create_database, populate_database
from cdedb.cli.storage import create_log, create_storage, populate_storage
from cdedb.cli.util import is_docker
from cdedb.config import SecretsConfig, TestConfig, set_configpath


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


def run_application_tests(testpatterns: List[str] = None, *,
                          verbose: bool = False) -> int:
    conf = TestConfig()
    secrets = SecretsConfig()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)

    create_log(conf)
    create_database(conf, secrets)
    populate_database(conf, secrets)

    # we need to setup the environment before we can import from cdedb or tests module
    import tests.backend_tests as backend_tests  # pylint: disable=import-outside-toplevel
    import tests.frontend_tests as frontend_tests  # pylint: disable=import-outside-toplevel
    import tests.other_tests as other_tests  # pylint: disable=import-outside-toplevel

    # load all tests which are not meant to be run separately (f.e. the ldap tests)
    test_modules = [backend_tests, frontend_tests, other_tests]
    test_suite = _load_tests(testpatterns, test_modules)

    unittest.installHandler()
    test_runner = MyTextTestRunner(verbosity=(2 if verbose else 1),
                                   resultclass=MyTextTestResult, descriptions=False)
    ran_tests = test_runner.run(test_suite)
    return 0 if ran_tests.wasSuccessful() else 1


def run_xss_tests(*, verbose: bool = False) -> int:
    conf = TestConfig()
    secrets = SecretsConfig()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)

    create_log(conf)
    create_storage(conf)
    populate_storage(conf)
    create_database(conf, secrets)
    populate_database(conf, secrets, xss=True)

    # we need to setup the environment before we can import from cdedb or tests module
    from bin.escape_fuzzing import (  # pylint: disable=import-outside-toplevel
        work as xss_check,
    )

    from cdedb.backend.entity_keeper import EntityKeeper
    from tests.common import BasicTest

    # setup the event keepers
    max_event_id = len(BasicTest.get_sample_data('event.events'))
    keeper = EntityKeeper(conf, 'event_keeper')
    for event_id in range(1, max_event_id + 1):
        keeper.init(event_id)
        keeper.commit(event_id, "", "Initialer Commit.")

    ret = xss_check(
        conf["XSS_OUTDIR"], verbose=verbose, payload=conf["XSS_PAYLOAD"],
        secondary_payload=conf["XSS_PAYLOAD_SECONDARY"]
    )

    return ret


def run_ldap_tests(testpatterns: List[str] = None, *, verbose: bool = False) -> int:
    conf = TestConfig()
    secrets = SecretsConfig()
    # prepare the translations
    subprocess.run(["make", "i18n-compile"], check=True, stdout=subprocess.DEVNULL)

    create_log(conf)
    if is_docker():
        # the database is already initialized, since it is needed to start the
        # ldap container in the first place
        print(f"Database {conf['CDB_DATABASE_NAME']} must already been set up.")
        # TODO verify this somehow
    else:
        create_database(conf, secrets)
        populate_database(conf, secrets)

        # update the current ldap setting
        # note that this takes no changes of the base ldap setup into account,
        # since this would need to reinstall slapd to work.
        subprocess.run(
            ["make", "ldap-update-full", f"DATABASE_NAME={conf['CDB_DATABASE_NAME']}"],
            check=True, stdout=subprocess.DEVNULL)

    # we need to setup the environment before we can import from cdedb or tests module
    import tests.ldap_tests as ldap_tests  # pylint: disable=import-outside-toplevel

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

    # if we specify 'default=["application"]', the application tests are always in parts
    # therefore, we defer the default handling after the args have been parsed
    parser.add_argument("--parts", action="extend", nargs="*", default=list(),
                        choices=["application", "ldap", "xss"],
                        help="choose which parts of the testsuite to run"
                             " (application tests are default)")

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

    # Set the promised default value if no parts were specified
    if not args.parts and not args.all_ldap:
        args.parts = ["application"]

    # Set args for presets.
    if args.first:
        args.testpatterns.append('tests.frontend_tests.[abcd]*')
    if args.second:
        args.testpatterns.append('tests.frontend_tests.[!abcd]*')
    if args.third:
        args.testpatterns.append('tests.backend_tests.*')
        args.testpatterns.append('tests.other_tests.*')
    # run the application tests only if there are presets
    if args.first or args.second or args.third:
        args.all = False
        args.all_application = False
        args.all_ldap = False
        args.parts = ["application"]

    return_code = 0

    # Run requested parts of the test suite.
    do_application = args.all or args.all_application or "application" in args.parts
    do_ldap = args.all or args.all_ldap or "ldap" in args.parts
    do_xss = args.all or "xss" in args.parts

    if do_application:
        # Override testpatterns to run all tests.
        if args.all or args.all_application:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        with CdEDBTestLock() as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            set_configpath(Lock.configpath)
            return_code += run_application_tests(
                testpatterns=testpatterns, verbose=args.verbose)

    if do_ldap:
        # Override testpatterns to run all tests.
        if args.all or args.all_ldap:
            testpatterns = None
        else:
            testpatterns = args.testpatterns

        with CdEDBTestLock("ldap") as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            set_configpath(Lock.configpath)
            return_code += run_ldap_tests(
                testpatterns=testpatterns, verbose=args.verbose)

    if do_xss:
        with CdEDBTestLock("xss") as Lock:
            assert Lock.thread is not None
            print(f"Using thread {Lock.thread}", file=sys.stderr)
            set_configpath(Lock.configpath)
            return_code += run_xss_tests(verbose=args.verbose)

    sys.exit(return_code)
