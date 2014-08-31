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
    def test_logout(self, user):
        self.assertEqual(
            user['displayname'],
            self.response.lxml.get_element_by_id('displayname').text_content())
        f = self.response.forms['logoutform']
        self.submit(f)
        self.assertNotIn(user['displayname'], self.response)
        self.assertIn('loginform', self.response.forms)

    @as_users("anton", "berta", "emilia")
    def test_showuser(self, user):
        self.traverse({'href' : '/mydata'})
        self.assertEqual("{} {}".format(user['given_names'],
                                        user['family_name']),
                         self.response.lxml.xpath('//h1/text()')[0])
        self.assertIn(user['given_names'], self.response.text)

    @as_users("anton")
    def test_adminshowuser(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = 2
        self.submit(f)
        berta = USER_DICT['berta']
        self.assertIn(berta['given_names'], self.response.text)

    @as_users("anton", "berta", "emilia")
    def test_change_password(self, user):
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
                if u in {"anton"}:
                    # admins are not resettable
                    self.assertEqual([], self.fetch_mail())
                    continue
                mail = self.fetch_mail()[0]
                for line in mail.split('\n'):
                    if line.startswith('zur'):
                        words = line.split(' ')
                        break
                index = words.index('nun')
                new_password = quopri.decodestring(words[index + 1])
                self.login(user)
                self.assertIn('loginform', self.response.forms)
                new_user = copy.deepcopy(user)
                new_user['password'] = new_password
                self.login(new_user)
                self.assertNotIn('loginform', self.response.forms)
                self.assertIn(user['displayname'], self.response)

    def test_admin_password_reset(self):
        anton = USER_DICT['anton']
        self.get('/')
        self.login(anton)
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = 2
        self.submit(f)
        f = self.response.forms['adminpasswordresetform']
        self.submit(f)
        mail = self.fetch_mail()[0]
        for line in mail.split('\n'):
            if line.startswith('zur'):
                words = line.split(' ')
                break
        index = words.index('nun')
        new_password = quopri.decodestring(words[index + 1])
        self.logout()
        berta = USER_DICT['berta']
        self.login(berta)
        self.assertIn('loginform', self.response.forms)
        new_berta = copy.deepcopy(berta)
        new_berta['password'] = new_password
        self.login(new_berta)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(new_berta['displayname'], self.response)

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user):
        new_username = "zelda@example.cde"
        self.traverse({'href' : '/mydata'},
                      {'href' : '/changeuser', 'index' : 0},
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

    def test_admin_username_change(self):
        new_username = "zelda@example.cde"
        anton = USER_DICT['anton']
        self.get('/')
        self.login(anton)
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = 2
        self.submit(f)
        self.traverse({'href' : '/changeuser', 'index' : 0},
                      {'href' : '/adminusernamechange'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = new_username
        self.submit(f)
        self.logout()
        berta = USER_DICT['berta']
        self.login(berta)
        self.assertIn('loginform', self.response.forms)
        new_berta = copy.deepcopy(berta)
        new_berta['username'] = new_username
        self.login(new_berta)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(new_berta['displayname'], self.response)
