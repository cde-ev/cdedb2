"""Contains some custom classes to run and display the tests on the command line."""

import unittest
from types import TracebackType
from typing import List, Optional, TextIO, Tuple, Type, Union

ExceptionInfo = Union[
    Tuple[Type[BaseException], BaseException, TracebackType],
    Tuple[None, None, None]
]


class MyTextTestRunner(unittest.TextTestRunner):
    """Subclass the TextTestRunner to provide a short command to re-run failed tests."""
    stream: TextIO

    def run(
        self, test: Union[unittest.TestSuite, unittest.TestCase]
    ) -> unittest.TestResult:
        result = super().run(test)
        failed = map(
            lambda error: error[0].id().split()[0],  # split to strip subtest paramters
            (result.errors + result.failures
             + [(unex_succ, "") for unex_succ in result.unexpectedSuccesses])
        )
        if not result.wasSuccessful():
            print("To rerun failed tests execute the following:", file=self.stream)
            print(f"/cdedb2/bin/check.py {' '.join(failed)}", file=self.stream)
        return result


class MyTextTestResult(unittest.TextTestResult):
    """Subclass the TextTestResult object to fix the CLI reporting.

    We keep track of the errors, failures and skips occurring in SubTests,
    and print a summary at the end of the TestCase itself.
    """
    stream: TextIO
    showAll: bool

    def __init__(self, stream: TextIO, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self._subTestErrors: List[ExceptionInfo] = []
        self._subTestFailures: List[ExceptionInfo] = []
        self._subTestSkips: List[str] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._subTestErrors = []
        self._subTestFailures = []
        self._subTestSkips = []

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase,
                   err: Optional[ExceptionInfo]) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None and err[0] is not None:
            if issubclass(err[0], subtest.failureException):
                errors = self._subTestFailures
            else:
                errors = self._subTestErrors
            errors.append(err)

    def stopTest(self, test: unittest.TestCase) -> None:
        super().stopTest(test)
        # Print a comprehensive list of failures and errors in subTests.
        output = []
        if self._subTestErrors:
            length = len(self._subTestErrors)
            if self.showAll:
                s = "ERROR" + (f"({length})" if length > 1 else "")
            else:
                s = "E" * length
            output.append(s)
        if self._subTestFailures:
            length = len(self._subTestFailures)
            if self.showAll:
                s = "FAIL" + (f"({length})" if length > 1 else "")
            else:
                s = "F" * length
            output.append(s)
        if self._subTestSkips:
            if self.showAll:
                s = "skipped {}".format(", ".join(
                    "{0!r}".format(r) for r in self._subTestSkips))
            else:
                s = "s" * len(self._subTestSkips)
            output.append(s)
        if output:
            if self.showAll:
                self.stream.writeln(", ".join(output))  # type: ignore
            else:
                self.stream.write("".join(output))
                self.stream.flush()

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        # Purposely override the parents method, to not print the skip here.
        super(unittest.TextTestResult, self).addSkip(test, reason)  # pylint: disable=bad-super-call
        self._subTestSkips.append(reason)
