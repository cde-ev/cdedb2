#!/usr/bin/env python3

import unittest
import copy
import quopri

from test.common import as_users, USER_DICT, FrontendTest

class TestCoreFrontend(FrontendTest):
    def test_login(self):
        for i, u in enumerate(("anton", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                self.get("/")
                f = self.response.forms['loginform']
                f['username'] = user['username']
                f['password'] = user['password']
                self.submit(f)
                self.assertEqual(
                    user['displayname'],
                    self.response.lxml.get_element_by_id('displayname').text_content())

    @as_users("anton", "berta", "emilia")
    def test_logout(self, user=None):
        self.assertEqual(
            user['displayname'],
            self.response.lxml.get_element_by_id('displayname').text_content())
        f = self.response.forms['logoutform']
        self.submit(f)
        self.assertNotIn(user['displayname'], self.response)
        self.assertIn('loginform', self.response.forms)

    @as_users("anton", "berta", "emilia")
    def test_mydata(self, user=None):
        self.get('/mydata')
        self.follow()
        self.assertEqual('Meine Daten',
                         self.response.lxml.xpath('//h1/text()')[0])
        self.assertIn(user['given_names'], self.response.text)

    @as_users("anton", "berta", "emilia")
    def test_change_password(self, user=None):
        new_password = 'krce84#(=kNO3xb'
        self.traverse({'href' : '/changepassword'})
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.logout()
        self.assertNotIn(user['displayname'], self.response)
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['password'] = new_password
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(user['displayname'], self.response)

    def test_reset_password(self):
        for i, u in enumerate(("anton", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                self.get('/')
                self.traverse({'href' : '/resetpassword'})
                f = self.response.forms['passwordresetform']
                f['email'] = user['username']
                self.submit(f)
                mail = self.fetch_mail()[0]
                link = None
                for line in mail.split('\n'):
                    if line.startswith('[1] '):
                        link = line[4:]
                link = quopri.decodestring(link).decode('utf-8')
                self.get(link)
                f = self.response.forms['passwordresetform']
                self.submit(f)
                if u in ("anton",):
                    # admins are not resettable
                    self.assertEqual(self.fetch_mail(), [])
                    continue
                mail = self.fetch_mail()[0]
                for line in mail.split('\n'):
                    if line.startswith('zur'):
                        words = line.split(' ')
                        break
                index = words.index('nun')
                new_password = words[index + 1]
                self.login(user)
                self.assertIn('loginform', self.response.forms)
                new_user = copy.deepcopy(user)
                new_user['password'] = new_password
                self.login(new_user)
                self.assertNotIn('loginform', self.response.forms)
                self.assertIn(user['displayname'], self.response)

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user=None):
        new_username = "zelda@example.cde"
        self.traverse({'href' : '/mydata'},
                      {'href' : '/changedata', 'index' : 0},
                      {'href' : '/changeusername'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = new_username
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        f = self.response.forms['usernamechangeform']
        f['password'] = user['password']
        self.submit(f)
        self.logout()
        self.assertNotIn(user['displayname'], self.response)
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['username'] = new_username
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(user['displayname'], self.response)
