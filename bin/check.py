#! /usr/bin/env python3

import argparse
import os
import pathlib
import subprocess
import sys
import unittest
from types import TracebackType
from typing import List, Optional, TextIO, Tuple, Type

# the directory containing the cdedb and tests modules
root = pathlib.Path(__file__).absolute().parent.parent
# add it to sys.path to make this script executable directly from everywhere
sys.path.append(str(root))
# this is necessary for calling make as subprocess
os.chdir(root)

from bin.test_runner_helpers import MyTextTestResult, MyTextTestRunner, check_test_setup
from tests.prepare_tests import prepare_environment


class CdEDBTestLock:
    """
    Simple lock mechanism to prevent multiple tests accessing the same
    test database and files simultaneously.
    """
    # Identifiers of existing test threads. Only truthy values allowed.
    # Take care that the database setup is configured accordingly.
    # TODO: improve this in #1948
    THREADS = (1, 2, 3, 4)

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


def _prepare_check(thread_id: int = 1) -> None:
    """Set the stage for running tests."""
    os.environ['CDEDB_TEST'] = "True"
    os.environ['CDEDB_TEST_DATABASE'] = f'cdb_test_{thread_id}'
    os.environ['CDEDB_TEST_TMP_DIR'] = f'/tmp/cdedb-test-{thread_id}'
    # TODO implement the following directly, don't use Makefile
    subprocess.run(('make', 'prepare-check'), check=True, stdout=subprocess.DEVNULL)


def check_xss(payload: str, thread_id: int = 1, verbose: bool = False,
              manual_preparation: bool = False) -> int:
    """Check for XSS vulnerabilites"""
    if not manual_preparation:
        os.environ['CDEDB_TEST_XSS_PAYLOAD'] = payload
        _prepare_check(thread_id=thread_id)
        subprocess.run(('make', 'storage-test'), check=True, stdout=subprocess.DEVNULL)
        subprocess.run(('make', 'sql-xss'), check=True, stdout=subprocess.DEVNULL)
    check_test_setup()

    command: Tuple[str, ...] = (
        'python3', '-m', 'bin.escape_fuzzing', '--payload', payload,
        '--dbname', os.environ['CDEDB_TEST_DATABASE'],
        '--storage-dir', os.environ['CDEDB_TEST_TMP_DIR'] + '/storage'
    )
    if verbose:
        command = command + ('--verbose', )
    ret = subprocess.run(command)
    return ret.returncode


def run_tests():
    pass


def run_regular_tests(configpath: pathlib.Path, testpatterns: List[str] = None, *,
                      verbose: bool = False) -> int:
    prepare_environment(configpath)

    if testpatterns:  # when no/empty pattern given, specify nothing to run full suite
        unittest.defaultTestLoader.testNamePatterns = [
            pattern if "*" in pattern else f"*{pattern}*" for pattern in testpatterns
        ]
    # TODO exclude ldap tests
    all_tests = unittest.defaultTestLoader.discover('tests', top_level_dir=str(root))

    unittest.installHandler()
    test_runner = MyTextTestRunner(verbosity=(2 if verbose else 1),
                                   resultclass=MyTextTestResult, descriptions=False)
    ran_tests = test_runner.run(all_tests)
    return 0 if ran_tests.wasSuccessful() else 1


def run_xss_tests():
    pass


def run_ldap_tests():
    pass


if __name__ == '__main__':
    configpath = root / "tests/config/test_1.py"
    os.environ['CDEDB_TEST_CONFIGPATH'] = str(configpath)
    # pattern = "test_dummy"
    # code = run_regular_tests(configpath, testpatterns=[pattern], verbose=True)
    code = run_regular_tests(configpath, verbose=True)
    exit()

    # parse arguments
    parser = argparse.ArgumentParser(
        description="Entry point to CdEDB's testing facilities.")
    parser.add_argument('testpatterns', default=[], nargs="*")

    test_options = parser.add_argument_group("general options")
    test_options.add_argument('--manual-preparation', action='store_true',
                              help="don't do test preparation")
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

    xss_options = parser.add_argument_group("XSS Options")
    xss_options.add_argument('--xss-check', '--xss', action='store_true',
                             help="check for xss vulnerabilities as implemented in"
                                  " bin/escape_fuzzing.py (Note that this ignores some"
                                  " other options, like --first)")
    xss_options.add_argument('--payload', type=str, default='<script>abcdef</script>',
                             help="Payload string to use for xss vulnerability check")

    parser.add_argument('--verbose', '-v', action='store_true',
                        help="more detailed output")
    args = parser.parse_args()

    # splitup in three parts with similar runtime
    if args.first:
        args.testpatterns.append('tests.test_frontend_[abcd]*')
    if args.second:
        args.testpatterns.append('tests.test_frontend_[!abcd]*')
    if args.third:
        args.testpatterns.append('tests.test_[!f]*')

    with CdEDBTestLock(args.thread_id) as Lock:
        assert Lock.thread_id is not None
        print(f"Using thread {Lock.thread_id}", file=sys.stderr)
        if args.xss_check:
            return_code = check_xss(
                args.payload, thread_id=Lock.thread_id, verbose=args.verbose,
                manual_preparation=args.manual_preparation)
        else:
            return_code = run_testsuite(
                args.testpatterns, thread_id=Lock.thread_id, verbose=args.verbose,
                manual_preparation=args.manual_preparation)

    sys.exit(return_code)
