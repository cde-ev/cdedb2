#!/usr/bin/env python3

import unittest
import unittest.mock

from test.common import as_users, USER_DICT, FrontendTest

class TestApplication(FrontendTest):
    def test_404(self):
        self.get("/nonexistentpath", status=404)
        self.assertTitle('404 Not Found: The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.')

    @as_users("berta")
    def test_403(self, user):
        self.get("/cde/semester/show", status=403)
        self.assertTitle('403 Forbidden: Access denied to CdEFrontend/show_semester.')

    def test_405(self):
        self.get("/core/login", status=405)
        self.assertTitle('405 Method Not Allowed: The method is not allowed for the requested URL.')

    def test_500(self):
        # Replace CoreFrontend.index() function with Mock that raises ValueError
        hander_mock = unittest.mock.MagicMock(
            side_effect=ValueError("a really unexpected exception"))
        hander_mock.modi = {"GET", "HEAD"}

        with unittest.mock.patch('cdedb.frontend.core.CoreFrontend.index',
                                 new=hander_mock),\
                unittest.mock.patch.object(self.app.app.conf, 'CDEDB_DEV', new=False):
            self.get('/', status=500)
            self.assertTitle("500 Internal Server Error: ValueError('a really unexpected exception')")
            self.assertPresence("ValueError")
            self.assertPresence("a really unexpected exception")

    def test_basics(self):
        self.get("/")
