#!/usr/bin/env python3

import unittest

from test.common import as_users, USER_DICT, FrontendTest

class TestEventFrontend(FrontendTest):
    @as_users("anton", "berta", "emilia")
    def test_index(self, user):
        self.traverse({'href' : '/event/'})

    @as_users("emilia")
    def test_showuser(self, user):
        self.traverse({'href' : '/mydata'})
        self.assertEqual("{} {}".format(user['given_names'],
                                        user['family_name']),
                         self.response.lxml.xpath('//h1/text()')[0])

    @as_users("emilia")
    def test_changeuser(self, user):
        self.traverse({'href' : '/mydata'}, {'href' : '/event/changeuser', 'index' : 0})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        self.submit(f)
        self.assertIn("Hyrule", self.response)
        self.assertEqual(
            "Zelda",
            self.response.lxml.get_element_by_id('displayname').text_content())
