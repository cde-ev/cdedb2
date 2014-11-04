#!/usr/bin/env python3

import unittest
import webtest

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

    def test_consent(self):
        user = USER_DICT["garcia"]
        self.login(user)
        self.assertEqual("Einwilligung zur Mitgliedersuche",
                         self.response.lxml.xpath('//h1/text()')[0])
        f = self.response.forms['toplaterform']
        self.submit(f)
        self.assertEqual("CdE Datenbank",
                         self.response.lxml.xpath('//h1/text()')[0])
        self.traverse({'href' : '/mydata'},
                      {'href' : '/cde/consentdecision'})
        f = self.response.forms['ackconsentform']
        self.submit(f)
        self.assertIn("successNotification", self.response.text)

    @as_users("anton", "berta")
    def test_get_foto(self, user):
        response = self.app.get('/cde/foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9')
        self.assertTrue(len(response.body) > 10000)

    @as_users("anton", "berta")
    def test_set_foto(self, user):
        self.traverse({'href' : '/mydata'}, {'href' : '/setfoto'})
        f = self.response.forms['setfotoform']
        f['foto'] = webtest.Upload("/tmp/cdedb-store/testfiles/picture.png")
        self.submit(f)
        self.assertIn('foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', self.response.text)
        with open('/tmp/cdedb-store/foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', 'rb') as f:
            blob = f.read()
        self.assertTrue(len(blob) > 10000)

    @as_users("anton", "berta")
    def test_member_search_single(self, user):
        self.traverse({'href' : '/membersearch'})
        self.assertEqual("Suche",
                         self.response.lxml.xpath('//h1/text()')[0])
        f = self.response.forms['membersearchform']
        f['qval_event_id'] = 1
        self.submit(f, button="updateform")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertIn("Im Garten 77", self.response.text)

    @as_users("anton", "berta")
    def test_member_search_accents(self, user):
        self.traverse({'href' : '/membersearch'})
        self.assertEqual("Suche",
                         self.response.lxml.xpath('//h1/text()')[0])
        f = self.response.forms['membersearchform']
        f['qval_event_id'] = 1
        self.submit(f, button="updateform")
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)
        self.assertIn("Im Garten 77", self.response.text)

    @as_users("anton", "berta")
    def test_member_search(self, user):
        self.traverse({'href' : '/membersearch'})
        self.assertEqual("Suche",
                         self.response.lxml.xpath('//h1/text()')[0])
        f = self.response.forms['membersearchform']
        f['qval_event_id'] = 1
        self.submit(f, button="updateform")
        f = self.response.forms['membersearchform']
        f['qval_username'] = "@example"
        self.submit(f)
        self.assertIn("Anton", self.response.text)
        self.assertIn("Bertålotta", self.response.text)

    @as_users("anton", "berta")
    def test_member_search_fulltext(self, user):
        self.traverse({'href' : '/membersearch'})
        self.assertEqual("Suche",
                         self.response.lxml.xpath('//h1/text()')[0])
        f = self.response.forms['membersearchform']
        f['qval_event_id'] = 1
        self.submit(f, button="updateform")
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "876 @example.cde"
        self.submit(f)
        self.assertIn("Anton", self.response.text)
        self.assertIn("Bertålotta", self.response.text)
