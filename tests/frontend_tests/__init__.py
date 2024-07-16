"""Module containing all CdEDB frontend tests, one file per frontend.

Parse (parsing of bank statements) and privacy tests have their own file, to group this
test of functionality at one place.
"""
from tests.frontend_tests.application import TestApplication as TestApplication
from tests.frontend_tests.assembly import (
    TestAssemblyFrontend as TestAssemblyFrontend,
    TestMultiAssemblyFrontend as TestMultiAssemblyFrontend,
)
from tests.frontend_tests.cde import TestCdEFrontend as TestCdEFrontend
from tests.frontend_tests.common import TestFrontendCommon as TestFrontendCommon
from tests.frontend_tests.core import TestCoreFrontend as TestCoreFrontend
from tests.frontend_tests.cron import TestCron as TestCron
from tests.frontend_tests.event import TestEventFrontend as TestEventFrontend
from tests.frontend_tests.ml import TestMlFrontend as TestMlFrontend
from tests.frontend_tests.parse import TestParseFrontend as TestParseFrontend
from tests.frontend_tests.privacy import TestPrivacyFrontend as TestPrivacyFrontend
