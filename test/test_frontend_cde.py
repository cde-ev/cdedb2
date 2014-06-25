#!/usr/bin/env python3

import unittest

from test.common import as_users, USER_DICT, FrontendTest

class TestCdEFrontend(FrontendTest):
    @as_users("anton", "berta")
    def test_mydata(self, user):
        self.traverse({'href' : '/mydata'})
        self.assertEqual('Meine Daten',
                         self.response.lxml.xpath('//h1/text()')[0])
        self.assertIn(user['given_names'], self.response.text)

    @as_users("anton", "berta")
    def test_changedata(self, user):
        self.traverse({'href' : '/mydata'}, {'href' : '/cde/changedata', 'index' : 0})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertIn("Hyrule", self.response)
        self.assertIn("Okarinas", self.response)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content())
