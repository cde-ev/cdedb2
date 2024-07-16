"""Module containing all remaining CdEDB tests.

This contains tests for our database interface, our middleware (like our config or
validation) and some special cases (like testing the offline instance, our scripting
interface or the session handling).
"""
from tests.other_tests.test_browser import TestBrowser as TestBrowser
from tests.other_tests.test_common import TestCommon as TestCommon
from tests.other_tests.test_config import TestConfig as TestConfig
from tests.other_tests.test_database import TestDatabase as TestDatabase
from tests.other_tests.test_huge_data import TestHugeData as TestHugeData
from tests.other_tests.test_offline import TestOffline as TestOffline
from tests.other_tests.test_script import TestScript as TestScript
from tests.other_tests.test_session import (
    TestMultiSessionFrontend as TestMultiSessionFrontend,
    TestSessionBackend as TestSessionBackend,
    TestSessionFrontend as TestSessionFrontend,
)
from tests.other_tests.test_validation import TestValidation as TestValidation
from tests.other_tests.test_vote_verification_script import (
    TestVerificationScript as TestVerificationScript,
)
