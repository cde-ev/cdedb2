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
                self.submit(f, check_notification=False)
                self.assertEqual(
                    user['display_name'],
                    self.response.lxml.get_element_by_id('displayname').text_content().strip())

    @as_users("anton", "berta", "emilia")
    def test_logout(self, user):
        self.assertEqual(
            user['display_name'],
            self.response.lxml.get_element_by_id('displayname').text_content().strip())
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False)
        self.assertNotIn(user['display_name'], self.response)
        self.assertIn('loginform', self.response.forms)

    @as_users("anton", "berta", "emilia")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        self.assertIn(user['given_names'], self.response.text)

    @as_users("anton")
    def test_adminshowuser(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        berta = USER_DICT['berta']
        self.assertTitle("Bertålotta Beispiel")

    @as_users("anton", "berta", "emilia")
    def test_change_password(self, user):
        new_password = 'krce84#(=kNO3xb'
        self.traverse({'href': '/core/self/show'})
        self.traverse({'href': '/core/self/password/change'})
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.logout()
        self.assertNotIn(user['display_name'], self.response)
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['password'] = new_password
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(user['display_name'], self.response)

    def test_reset_password(self):
        new_password = "krce63koLe#$e"
        for i, u in enumerate(("anton", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                self.get('/')
                self.traverse({'href': '/core/password/reset'})
                self.assertTitle("Passwort zurücksetzen")
                f = self.response.forms['passwordresetform']
                f['email'] = user['username']
                self.submit(f)
                self.assertTitle("CdE Datenbank")
                mail = self.fetch_mail()[0]
                link = None
                for line in mail.split('\n'):
                    if line.startswith('[1] '):
                        link = line[4:]
                link = quopri.decodestring(link).decode('utf-8')
                self.get(link)
                self.follow()
                self.assertTitle("Passwort zurücksetzen -- Bestätigung")
                f = self.response.forms['passwordresetform']
                f['new_password'] = new_password
                if u in {"anton"}:
                    self.submit(f, check_notification=False)
                    ## admins are not resettable
                    self.assertEqual([], self.fetch_mail())
                    continue
                else:
                    self.submit(f)
                self.login(user)
                self.assertIn('loginform', self.response.forms)
                new_user = copy.deepcopy(user)
                new_user['password'] = new_password
                self.login(new_user)
                self.assertNotIn('loginform', self.response.forms)
                self.assertIn(user['display_name'], self.response)

    def test_admin_password_reset(self):
        anton = USER_DICT['anton']
        self.get('/')
        self.login(anton)
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
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
        self.assertIn(new_berta['display_name'], self.response)

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user):
        new_username = "zelda@example.cde"
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/username/change'})
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
        self.assertNotIn(user['display_name'], self.response)
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['username'] = new_username
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertIn(user['display_name'], self.response)

    def test_admin_username_change(self):
        new_username = "zelda@example.cde"
        anton = USER_DICT['anton']
        self.get('/')
        self.login(anton)
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.traverse({'href': '/username/adminchange'})
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
        self.assertIn(new_berta['display_name'], self.response)

    @as_users("anton")
    def test_privilege_change(self,  user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'href': '/persona/2/privileges'})
        self.assertTitle("Administration -- Privilegien ändern für Bertålotta Beispiel")
        f = self.response.forms['privilegechangeform']
        self.assertEqual(False, f['is_admin'].checked)
        self.assertEqual(False, f['is_core_admin'].checked)
        self.assertEqual(False, f['is_cde_admin'].checked)
        f['is_core_admin'].checked = True
        f['is_cde_admin'].checked = True
        self.submit(f)
        self.traverse({'href': '/persona/2/privileges'})
        self.assertTitle("Administration -- Privilegien ändern für Bertålotta Beispiel")
        f = self.response.forms['privilegechangeform']
        self.assertEqual(False, f['is_admin'].checked)
        self.assertEqual(True, f['is_core_admin'].checked)
        self.assertEqual(True, f['is_cde_admin'].checked)

    @as_users("anton")
    def test_user_search(self,  user):
        self.traverse({'href': '/core/search/user/form'})
        self.assertTitle("Allgemeine Nutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_username'] = 'n'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Allgemeine Nutzersuche -- 5 Ergebnisse gefunden")
        self.assertIn("Jalapeño", self.response.text)

    @as_users("anton")
    def test_archived_user_search(self,  user):
        self.traverse({'href': '/core/search/archiveduser/form'})
        self.assertTitle("Archivnutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_given_names'] = 'des'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivnutzersuche -- 1 Ergebnis gefunden")
        self.assertIn("Hell", self.response.text)

    def test_log(self):
        ## First: generate data
        self.test_admin_password_reset()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Start', 'href': '^/d?b?/?$'},
                      {'href': '/core/log'})
        self.assertTitle("\nAccounts -- Logs (0--2)\n")
