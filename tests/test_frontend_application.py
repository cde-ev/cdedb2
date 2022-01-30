#!/usr/bin/env python3
# pylint: disable=missing-module-docstring

import unittest.mock
from typing import Any

from tests.common import FrontendTest, as_users


class TestApplication(FrontendTest):
    def test_404_anonymous(self) -> None:
        self.get("/nonexistentpath", status=404)
        self.assertTitle("404: Not Found")
        self.assertPresence("Index", div="navbar-collapse-1")
        self.assertPresence("Veranstaltungen", div="navbar-collapse-1")
        self.assertNonPresence("Mitglieder", div="navbar-collapse-1")
        self.assertNonPresence("Mailinglisten", div="navbar-collapse-1")
        self.assertNonPresence("Versammlungen", div="navbar-collapse-1")
        self.assertNonPresence("", div="displayname", check_div=False)

    @as_users("berta")
    def test_404(self) -> None:
        self.get("/nonexistentpath", status=404)
        self.assertTitle("404: Not Found")
        self.assertPresence("Index", div="navbar-collapse-1")
        self.assertPresence("Mitglieder", div="navbar-collapse-1")
        self.assertPresence("Veranstaltungen", div="navbar-collapse-1")
        self.assertPresence("Mailinglisten", div="navbar-collapse-1")
        self.assertPresence("Versammlungen", div="navbar-collapse-1")
        self.assertPresence(self.user["display_name"], div="displayname")

    @as_users("berta")
    def test_403(self) -> None:
        self.get("/cde/semester/show", status=403)
        self.assertTitle('403: Forbidden')

    def test_405(self) -> None:
        self.get("/core/login", status=405)
        self.assertTitle('405: Method Not Allowed')

    @as_users("berta")
    def test_500_before_user_lookup(self) -> None:
        with unittest.mock.patch(
            'cdedb.backend.session.SessionBackend.lookupsession'
        ) as lookup_mock, unittest.mock.patch(
            'cdedb.config.BasicConfig.__getitem__'
        ) as config_mock:

            # make SessionBackend.lookupsession() raise a ValueError
            lookup_mock.side_effect = ValueError("a really unexpected exception")

            # pretend we are not in testmode to create an error page
            def config_mock_getitem(key: str) -> Any:
                if key in ["CDEDB_DEV", "CDEDB_TEST"]:
                    return False
                return self.app.app.conf._configchain[key]  # pylint: disable=protected-access
            config_mock.side_effect = config_mock_getitem

            self.get('/', status=500)

        self.assertTitle("500: Internal Server Error")
        self.assertPresence("ValueError", div='static-notifications')
        self.assertPresence("Index", div="navbar-collapse-1")
        self.assertPresence("Veranstaltungen", div="navbar-collapse-1")
        self.assertNonPresence("Mitglieder", div="navbar-collapse-1")
        self.assertNonPresence("Mailinglisten", div="navbar-collapse-1")
        self.assertNonPresence("Versammlungen", div="navbar-collapse-1")
        self.assertNonPresence("", div="displayname", check_div=False)

    @as_users("berta")
    def test_500(self) -> None:
        with unittest.mock.patch(
            'cdedb.frontend.core.CoreFrontend.index'
        ) as index_mock, unittest.mock.patch(
            'cdedb.config.BasicConfig.__getitem__'
        ) as config_mock:

            # make CoreFrontend.index() raise a ValueError
            index_mock.side_effect = ValueError("a really unexpected exception")
            index_mock.modi = {"GET", "HEAD"}  # TODO preserve modi despite mock

            # pretend we are not in testmode to create an error page
            def config_mock_getitem(key: str) -> Any:
                if key in ["CDEDB_DEV", "CDEDB_TEST"]:
                    return False
                return self.app.app.conf._configchain[key]  # pylint: disable=protected-access
            config_mock.side_effect = config_mock_getitem

            self.get('/', status=500)

        self.assertTitle("500: Internal Server Error")
        self.assertPresence("ValueError", div="static-notifications")
        self.assertPresence("Index", div="navbar-collapse-1")
        self.assertPresence("Veranstaltungen", div="navbar-collapse-1")
        self.assertPresence("Mitglieder", div="navbar-collapse-1")
        self.assertPresence("Mailinglisten", div="navbar-collapse-1")
        self.assertPresence("Versammlungen", div="navbar-collapse-1")
        self.assertPresence(self.user["display_name"], div="displayname")

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
    def test_csrf_mitigation(self) -> None:
        self.get("/core/self/change")
        f = self.response.forms['changedataform']
        # Try submitting with missing anti CSRF token
        f['_anti_csrf'] = None
        f['postal_code2'] = "22337"
        self.submit(f, check_notification=False)
        self.assertPresence("Dieses Formular benötigt einen Anti-CSRF-Token.",
                            div='notifications')
        self.get("/core/self/show")
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
