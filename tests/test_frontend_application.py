#!/usr/bin/env python3

from typing import Any
import unittest.mock

from cdedb.common import CdEDBObject
from tests.common import FrontendTest, as_users


class TestApplication(FrontendTest):
    def test_404(self) -> None:
        self.get("/nonexistentpath", status=404)
        self.assertTitle('404: Not Found')

    @as_users("berta")
    def test_403(self, user: CdEDBObject) -> None:
        self.get("/cde/semester/show", status=403)
        self.assertTitle('403: Forbidden')

    def test_405(self) -> None:
        self.get("/core/login", status=405)
        self.assertTitle('405: Method Not Allowed')

    @unittest.mock.patch('cdedb.config.BasicConfig.__getitem__')
    @unittest.mock.patch('cdedb.frontend.core.CoreFrontend.index')
    def test_500(self, hander_mock: unittest.mock.Mock,
                 config_mock: unittest.mock.Mock) -> None:
        # Replace CoreFrontend.index() function with Mock that raises ValueError
        hander_mock.side_effect = ValueError("a really unexpected exception")
        hander_mock.modi = {"GET", "HEAD"}  # TODO set modi automatically

        def config_mock_getitem(key: str) -> Any:
            if key in ["CDEDB_DEV", "CDEDB_TEST"]:
                return False
            return self.app.app.conf._configchain[key]
        config_mock.side_effect = config_mock_getitem

        self.get('/', status=500)
        self.assertTitle("500: Internal Server Error")
        self.assertPresence("ValueError", div='static-notifications')

    def test_error_catching(self) -> None:
        """
        This test checks that errors risen from within the CdEDB Python code
        are correctly caught by the test framework. Otherwise we cannot rely
        on the completness of our tests.
        """
        # Replace CoreFrontend.index() function with Mock that raises
        # ValueError
        hander_mock = unittest.mock.MagicMock(
            side_effect=ValueError("a really unexpected exception"))
        hander_mock.modi = {"GET", "HEAD"}

        with unittest.mock.patch('cdedb.frontend.core.CoreFrontend.index',
                                 new=hander_mock):
            with self.assertRaises(ValueError,
                                   msg="The test suite did not detect an "
                                       "unexpected exception. Be careful with "
                                       "the test results, as they may not "
                                       "report all errors in the application."):
                self.get('/', status='*')

    def test_basics(self) -> None:
        self.get("/")

    @as_users("anton")
    def test_csrf_mitigation(self, user: CdEDBObject) -> None:
        self.get("/core/self/change")
        f = self.response.forms['changedataform']
        # Try submitting with missing anti CSRF token
        f['_anti_csrf'] = None
        f['postal_code2'] = "22337"
        self.submit(f, check_notification=False)
        self.assertPresence("Dieses Formular benötigt einen Anti-CSRF-Token.",
                            div='notifications')
        self.get("/core/self/show")
        self.follow()
        self.assertNonPresence("22337")

        # Try submitting with invalid anti CSRF token hash
        self.get("/core/self/change")
        f = self.response.forms['changedataform']
        f['_anti_csrf'] = "000000000000000000000000000000000000000000000000000000000" \
                          "000000000000000000000000000000000000000000000000000000000" \
                          "00000000000000--2200-01-01 00:00:00+0000--1"
        f['postal_code2'] = "abcd"
        self.submit(f, check_notification=False)
        self.assertPresence("Der Anti-CSRF-Token wurde gefälscht.",
                            div='notifications')
        # Try re-submitting with valid anti CSRF token, but validation errors
        f = self.response.forms['changedataform']
        self.submit(f, check_notification=False)
        self.assertPresence("Validierung fehlgeschlagen.", div='notifications')
        f = self.response.forms['changedataform']
        f['postal_code2'] = "22337"
        self.submit(f)
        self.assertPresence("22337")
