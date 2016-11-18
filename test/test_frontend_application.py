#!/usr/bin/env python3

import unittest

from test.common import as_users, USER_DICT, FrontendTest

class TestApplication(FrontendTest):
    def test_404(self):
        self.get("/nonexistentpath", status=404)
        self.assertTitle('Oops')

    @as_users("berta")
    def test_403(self, user):
        self.get("/cde/semester/show", status=403)
        self.assertTitle('Oops')

    def test_wrong_post(self):
        self.get("/core/login", status=405)

    def test_basics(self):
        self.get("/")

    @unittest.expectedFailure
    def test_error_fail(self):
        self.get("/error?kind=backend")

    def test_error(self):
        self.response = self.app.get("/error?kind=backend")
        self.assertTitle('Fehler')
