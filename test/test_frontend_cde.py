#!/usr/bin/env python3

import unittest

from test.common import as_users, USER_DICT, FrontendTest

class TestCdEFrontend(FrontendTest):
    @as_users("anton", "berta")
    def test_index(self, user):
        self.traverse({'href' : '/cde/$'})

    @as_users("anton", "berta")
    def test_showuser(self, user):
        self.traverse({'href' : '/mydata'})
        self.assertEqual("{} {}".format(user['given_names'],
                                        user['family_name']),
                         self.response.lxml.xpath('//h1/text()')[0])
        if user['id'] == 2:
            self.assertIn('PfingstAkademie', self.response.text)

    @as_users("anton", "berta")
    def test_changedata(self, user):
        self.traverse({'href' : '/mydata'}, {'href' : '/cde/changeuser', 'index' : 0})
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

    @as_users("anton", "berta")
    def test_changedata(self, user):
        self.traverse({'href' : '/mydata'}, {'href' : '/cde/changeuser', 'index' : 0})
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

    def test_changelog(self):
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href' : '/mydata'}, {'href' : '/cde/changeuser', 'index' : 0})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        self.submit(f)
        self.assertIn(user['family_name'], self.response.text)
        self.assertNotIn('Ganondorf', self.response.text)
        self.logout()
        user = USER_DICT["anton"]
        self.login(user)
        self.traverse({'href' : '/cde/listpendingchanges'})
        self.assertEqual("Zurzeit liegen 1 Änderungen vor",
                         self.response.lxml.xpath('//h1/text()')[0])
        self.traverse({'href' : '/cde/inspectchange'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertEqual("Zurzeit liegen 0 Änderungen vor",
                         self.response.lxml.xpath('//h1/text()')[0])
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href' : '/mydata'})
        self.assertNotIn(user['family_name'], self.response.text)
        self.assertIn('Ganondorf', self.response.text)
