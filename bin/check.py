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


class CdEDBTestLock():
    """
    Simple lock mechanism to prevent multiple tests accessing the same
    test database and files simultaneously.
    """
    # Identifiers of existing test threads. Only truthy values allowed.
    # Take care that the database setup is configured accordingly.
    # TODO: improve this in #1948
    THREADS = (1, 2, 3, 4)

    thread_id: int
    lockfile: TextIO

    def __init__(self, thread_id: int = 0):
        self.thread_id = thread_id

    def _get_lockfile_path(self) -> pathlib.Path:
        return pathlib.Path('/tmp') / f'cdedb-test-{self.thread_id}.lock'

    def acquire(self) -> None:
        """Lock the thread"""
        if self.thread_id:
            if self.thread_id not in self.THREADS:
                raise RuntimeError("Invalid thread id")
            try:
                self.lockfile = open(self._get_lockfile_path(), 'x')
                return
            except FileExistsError:
                raise RuntimeError(f"Thread {self.thread_id} is currently in use.")
        else:
            for thread_id in self.THREADS:
                try:
                    self.thread_id = thread_id
                    self.lockfile = open(self._get_lockfile_path(), 'x')
                    return
                except FileExistsError:
                    continue
            self.thread_id = 0
            raise RuntimeError("All threads are currently in use.")

    def release(self) -> None:
        """Unlock the thread"""
        self.lockfile.close()
        self._get_lockfile_path().unlink()

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


def run_testsuite(testpatterns: List[str] = None, *, thread_id: int = 1,
                  manual_preparation: bool = False) -> int:
    # TODO: implement/configure parallel testing
    if not manual_preparation:
        _prepare_check(thread_id=thread_id)
    check_test_setup()

    if testpatterns:  # when no/empty pattern given, specify nothing to run full suite
        unittest.defaultTestLoader.testNamePatterns = [
            pattern if "*" in pattern else f"*{pattern}*" for pattern in testpatterns
        ]
    all_tests = unittest.defaultTestLoader.discover('tests', top_level_dir=str(root))

    unittest.installHandler()
    test_runner = MyTextTestRunner(
        verbosity=2, resultclass=MyTextTestResult, descriptions=False)
    ran_tests = test_runner.run(all_tests)
    return 0 if ran_tests.wasSuccessful() else 1


if __name__ == '__main__':
    # parse arguments
    # TODO: some of the help texts can be improved
    parser = argparse.ArgumentParser(description="Entry point to CdEDB's"
                                                 " testing facilities.")
    parser.add_argument('testpatterns', default="", nargs="*")

    test_options = parser.add_argument_group("general options")
    test_options.add_argument('--manual-preparation', action='store_true',
                              help="don't do test preparation")
    thread_options = test_options.add_mutually_exclusive_group()
    thread_options.add_argument(
        '--thread-id', type=int, choices=(1, 2, 3, 4), default=0, metavar="INT",
        help="ID of thread to use for run (optional, if not given, choose free thread"
             " automatically)")
    thread_options.add_argument('--threads', type=int, choices=(1, 2, 3), default=1,
                                metavar="NUMBER", help="number of threads to use")

    xss_options = parser.add_argument_group("XSS Options")
    xss_options.add_argument('--xss-check', '--xss', action='store_true',
                             help="check for xss vulnerabilities as implemented in "
                                  "bin/escape_fuzzing.py (Note that this ignores some"
                                  " other options, like --threads)")
    xss_options.add_argument('--payload', type=str, default='<script>abcdef</script>',
                             help="Payload string to use for xss vulnerability check")

    parser.add_argument('--verbose', '-v', action='store_true',
                        help="more detailed output")
    # TODO: implement verbosity settings -v and -q (-v currently only used for xss)
    args = parser.parse_args()

    with CdEDBTestLock(args.thread_id) as Lock:
        print(f"Using thread {Lock.thread_id}", file=sys.stderr)
        if args.xss_check:
            return_code = check_xss(args.payload, thread_id=Lock.thread_id,
                                    verbose=args.verbose,
                                    manual_preparation=args.manual_preparation)
        else:
            return_code = run_testsuite(args.testpatterns, thread_id=Lock.thread_id,
                                        manual_preparation=args.manual_preparation)

    sys.exit(return_code)
