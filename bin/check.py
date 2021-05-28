#! /usr/bin/env python3

import argparse
import os
import pathlib
import subprocess
import sys
import unittest
from typing import List, Tuple

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
    thread_id: int
    lockfile: pathlib.Path

    def __init__(self, thread_id: int):
        self.thread_id = thread_id
        self.lockfile = pathlib.Path('/tmp') / f'cdedb-test-{self.thread_id}.lock'

    def acquire(self) -> bool:
        """Lock the thread

        :returns: whether locking was successful.
        """
        if self.lockfile.exists():
            return False
        else:
            self.lockfile.touch()
            return True

    def release(self) -> None:
        """Unlock the thread"""
        self.lockfile.unlink()


def _find_free_thread() -> int:
    """Find a test thread which is not locked yet and lock it.

    :returns: an id of a free test thread
    :raises: RuntimeError if all threads are locked
    """
    for test_id in range(1,5):
        Lock = CdEDBTestLock(test_id)
        if Lock.acquire():
            return test_id
    raise RuntimeError("All threads are currently in use. If you are sure that not, fix"
                       " it manually by removing the lock file(s) from /tmp. For"
                       " resetting everything, run `make sample-data`.")


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

    CdEDBTestLock(thread_id).release()
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

    if args.thread_id:
        thread_id = args.thread_id
        Lock = CdEDBTestLock(thread_id)
        if not Lock.acquire():
            raise RuntimeError("The thread you want to use is currently in use.")
    else:
        thread_id = _find_free_thread()
        print(f"Using thread {thread_id}")
    if args.xss_check:
        return_code = check_xss(args.payload, thread_id=thread_id,
                                verbose=args.verbose,
                                manual_preparation=args.manual_preparation)
    else:
        return_code = run_testsuite(args.testpatterns, thread_id=thread_id,
                                    manual_preparation=args.manual_preparation)
    sys.exit(return_code)
