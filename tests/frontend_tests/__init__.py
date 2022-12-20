"""Module containing all CdEDB frontend tests, one file per frontend.

Parse (parsing of bank statements) and privacy tests have their own file, to group this
test of functionality at one place.
"""
from tests.frontend_tests.application import TestApplication
from tests.frontend_tests.assembly import (
    TestAssemblyFrontend, TestMultiAssemblyFrontend,
)
from tests.frontend_tests.cde import TestCdEFrontend
from tests.frontend_tests.common import TestFrontendCommon
from tests.frontend_tests.core import TestCoreFrontend
from tests.frontend_tests.cron import TestCron
from tests.frontend_tests.event import TestEventFrontend
from tests.frontend_tests.ml import TestMlFrontend
from tests.frontend_tests.parse import TestParseFrontend
from tests.frontend_tests.privacy import TestPrivacyFrontend
