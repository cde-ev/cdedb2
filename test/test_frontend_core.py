#!/usr/bin/env python3

import unittest
import copy
import json
import quopri
import webtest

from test.common import as_users, USER_DICT, FrontendTest
from cdedb.query import QueryOperators

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
        self.assertNonPresence(user['display_name'])
        self.assertIn('loginform', self.response.forms)

    @as_users("anton", "berta", "emilia")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        self.assertPresence(user['given_names'])

    @as_users("anton")
    def test_adminshowuser(self, user):
        self.admin_view_profile('berta')
        berta = USER_DICT['berta']
        self.assertTitle("Bertålotta Beispiel")

    @as_users("anton")
    def test_selectpersona(self, user):
        self.get('/core/persona/select?kind=persona&phrase=din')
        expectation = {
            'personas': [{'display_name': 'Daniel',
                          'email': 'daniel@example.cde',
                          'id': 4,
                          'name': 'Daniel D. Dino'},
                          {'display_name': 'Ferdinand',
                           'email': 'ferdinand@example.cde',
                           'id': 6,
                           'name': 'Ferdinand F. Findus'}]}
        self.assertEqual(expectation, self.response.json)
        self.get('/core/persona/select?kind=mod_ml_user&phrase=@exam&aux=5')
        expectation = (1, 2, 3, 5, 6, 7, 9, 11)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("anton")
    def test_adminshowuser_advanced(self, user):
        for phrase, title in (("DB-2-H", "Bertålotta Beispiel"),
                              ("2", "Bertålotta Beispiel"),
                              ("Bertålotta Beispiel", "Bertålotta Beispiel"),
                              ("berta@example.cde", "Bertålotta Beispiel"),
                              ("anton@example.cde", "Anton Armin A. Administrator"),
                              ("Spielmanns", "Bertålotta Beispiel"),):
            self.traverse({'href': '^/$'}, {'href': '/core/search/user'})
            f = self.response.forms['adminshowuserform']
            f['phrase'] = phrase
            self.submit(f)
            self.assertTitle(title)
        self.traverse({'href': '^/$'}, {'href': '/core/search/user'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "nonsense asorecuhasoecurhkgdgdckgdoao"
        self.submit(f)
        self.assertTitle("CdE Datenbank")
        self.traverse({'href': '^/$'}, {'href': '/core/search/user'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "@example.cde"
        self.submit(f)
        self.assertTitle("Allgemeine Nutzerverwaltung")
        self.assertPresence("Bertålotta")
        self.assertPresence("Emilia")
        self.assertPresence("Garcia")
        self.assertPresence("Kalif")

    @as_users("anton", "berta", "garcia")
    def test_changedata(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location'] = "Hyrule"
        f['country'] = "Arcadia"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertTitle("{} {}".format(user['given_names'], user['family_name']))
        self.assertPresence("Hyrule")
        self.assertPresence("Okarinas")
        self.assertPresence("Zelda")

    @as_users("anton")
    def test_adminchangedata(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933")

    @as_users("anton")
    def test_adminchangedata2(self, user):
        self.admin_view_profile('anton')
        self.traverse({'href': '/core/persona/1/adminchange'})
        self.assertTitle("Anton Armin A. Administrator bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Anton Armin A. Administrator")
        self.assertPresence("03.04.1933")

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
        self.assertNonPresence(user['display_name'])
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['password'] = new_password
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(user['display_name'])

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
                if u in {"anton"}:
                    ## admins are not resettable
                    self.assertEqual([], self.fetch_mail())
                    continue
                mail = self.fetch_mail()[0]
                link = None
                for line in mail.split('\n'):
                    if line.startswith('[1] '):
                        link = line[4:]
                link = quopri.decodestring(link).decode('utf-8')
                self.get(link)
                self.follow()
                self.assertTitle("Neues Passwort setzen")
                f = self.response.forms['passwordresetform']
                f['new_password'] = new_password
                f['new_password2'] = new_password
                self.submit(f)
                self.login(user)
                self.assertIn('loginform', self.response.forms)
                new_user = copy.deepcopy(user)
                new_user['password'] = new_password
                self.login(new_user)
                self.assertNotIn('loginform', self.response.forms)
                self.assertLogin(user['display_name'])

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
        self.assertIn('loginform', self.response.forms)
        self.login(user)
        self.assertIn('loginform', self.response.forms)
        new_user = copy.deepcopy(user)
        new_user['username'] = new_username
        self.login(new_user)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(user['display_name'])

    def test_admin_username_change(self):
        new_username = "zelda@example.cde"
        anton = USER_DICT['anton']
        self.get('/')
        self.login(anton)
        self.admin_view_profile('berta')
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
        self.assertLogin(new_berta['display_name'])

    @as_users("anton")
    def test_privilege_change(self,  user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/persona/2/privileges'})
        self.assertTitle("Privilegien ändern für Bertålotta Beispiel")
        f = self.response.forms['privilegechangeform']
        self.assertEqual(False, f['is_admin'].checked)
        self.assertEqual(False, f['is_core_admin'].checked)
        self.assertEqual(False, f['is_cde_admin'].checked)
        f['is_core_admin'].checked = True
        f['is_cde_admin'].checked = True
        self.submit(f)
        self.traverse({'href': '/persona/2/privileges'})
        self.assertTitle("Privilegien ändern für Bertålotta Beispiel")
        f = self.response.forms['privilegechangeform']
        self.assertEqual(False, f['is_admin'].checked)
        self.assertEqual(True, f['is_core_admin'].checked)
        self.assertEqual(True, f['is_cde_admin'].checked)

    @as_users("anton", "berta")
    def test_get_foto(self, user):
        response = self.app.get('/core/foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9')
        self.assertTrue(response.body.startswith(b"\x89PNG"))
        self.assertTrue(len(response.body) > 10000)

    @as_users("anton", "berta")
    def test_set_foto(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/foto/change'})
        f = self.response.forms['setfotoform']
        with open("/tmp/cdedb-store/testfiles/picture.png", 'rb') as datafile:
            data = datafile.read()
        f['foto'] = webtest.Upload("picture.png", data, "application/octet-stream")
        self.submit(f)
        self.assertIn('foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', self.response.text)
        with open('/tmp/cdedb-store/foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', 'rb') as f:
            blob = f.read()
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertTrue(len(blob) > 10000)

    @as_users("anton", "berta")
    def test_set_foto_jpg(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/foto/change'})
        f = self.response.forms['setfotoform']
        with open("/tmp/cdedb-store/testfiles/picture.jpg", 'rb') as datafile:
            data = datafile.read()
        f['foto'] = webtest.Upload("picture.jpg", data, "application/octet-stream")
        self.submit(f)
        self.assertIn('foto/5bf9f9d6ce9cb9dbe96623076fac56b631ba129f2d47a497f9adc1b0b8531981bb171e191856ebc37249485136f214c837ae871c1389152a9e956a447b08282e', self.response.text)
        with open('/tmp/cdedb-store/foto/5bf9f9d6ce9cb9dbe96623076fac56b631ba129f2d47a497f9adc1b0b8531981bb171e191856ebc37249485136f214c837ae871c1389152a9e956a447b08282e', 'rb') as f:
            blob = f.read()
        self.assertTrue(blob.startswith(b"\xff\xd8\xff"))
        self.assertTrue(len(blob) > 10000)

    @as_users("berta")
    def test_reset_foto(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertIn('foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', self.response.text)
        self.traverse({'href': '/foto/change'})
        f = self.response.forms['resetfotoform']
        self.submit(f)
        self.assertNotIn('foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', self.response.text)

    @as_users("anton")
    def test_user_search(self,  user):
        self.traverse({'href': '/core/search/user'})
        self.assertTitle("Allgemeine Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.similar.value
        f['qval_username'] = 'n'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Allgemeine Nutzerverwaltung")
        self.assertPresence("Ergebnis [5]")
        self.assertPresence("Jalapeño")

    @as_users("anton")
    def test_archived_user_search(self,  user):
        self.traverse({'href': '/core/search/archiveduser'})
        self.assertTitle("Archivnutzersuche")
        f = self.response.forms['queryform']
        f['qop_given_names'] = QueryOperators.similar.value
        f['qval_given_names'] = 'des'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivnutzersuche")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Hell")

    @as_users("anton")
    def test_archived_user_search2(self, user):
        self.traverse({'href': '/core/search/archiveduser'})
        self.assertTitle("Archivnutzersuche")
        f = self.response.forms['queryform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivnutzersuche")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Hell")

    @as_users("anton")
    def test_show_archived_user(self, user):
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.")

    @as_users("anton")
    def test_meta_info(self, user):
        self.traverse({'href': '^/$'},
                      {'href': '/meta'})
        self.assertTitle("Allgemeine Metainformationen")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Bertålotta Beispiel", f["Finanzvorstand_Name"].value)
        f["Finanzvorstand_Name"] = "Zelda"
        self.submit(f)
        self.assertTitle("Allgemeine Metainformationen")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Zelda", f["Finanzvorstand_Name"].value)

    def test_changelog(self):
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        self.submit(f, check_notification=False)
        self.assertPresence(user['family_name'])
        self.assertNonPresence('Ganondorf')
        self.logout()
        user = USER_DICT["anton"]
        self.login(user)
        self.traverse({'href': '^/$'}, {'href': '/core/changelog/list'})
        self.assertTitle("Zu prüfende Profiländerungen [1]")
        self.traverse({'href': '/core/persona/2/changelog/inspect'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Zu prüfende Profiländerungen [0]")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence(user['family_name'])
        self.assertPresence('Ganondorf')

    @as_users("anton")
    def test_history(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933")
        self.traverse({'href': '/core/persona/2/history'})
        self.assertTitle("Geschichte von Bertålotta Beispiel")
        self.assertPresence(r"Gen 2\W*03.04.1933", regex=True)
        self.assertPresence(r"Gen 1\W*11.02.1981", regex=True)

    @as_users("anton")
    def test_rst(self, user):
        self.admin_view_profile('inga')
        self.assertIn('<div class="section" id="CDEDB_RST_inga">',
                      self.response.text)

    @as_users("anton")
    def test_trivial_promotion(self, user):
        self.admin_view_profile('emilia')
        self.traverse({'href': '/core/persona/5/promote'})
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['realmselectionform']
        self.assertNotIn("event", f['target_realm'].options)
        f['target_realm'] = "cde"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['promotionform']
        self.submit(f)
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("Guthaben")

    @as_users("anton")
    def test_nontrivial_promotion(self, user):
        self.admin_view_profile('kalif')
        self.traverse({'href': '/core/persona/11/promote'})
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        f = self.response.forms['realmselectionform']
        f['target_realm'] = "event"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        f = self.response.forms['promotionform']
        f['birthday'] = "21.6.1977"
        f['gender'] = 1
        self.submit(f)
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")
        self.assertPresence("Geburtstag")

    def test_genesis_event(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/core/genesis/request'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "event"
        f['gender'] = "1"
        f['birthday'] = "5.6.1987"
        f['address'] = "An der Eiche"
        f['postal_code'] = "12345"
        f['location'] = "Marcuria"
        f['country'] = "Arkadien"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertNonPresence("zorro@example.cde")
        self.assertNonPresence("Zur Zeit liegen keine Veranstaltungs-Anfragen vor")
        self.assertPresence("Zur Zeit liegen keine Mailinglisten-Anfragen vor")
        self.traverse({'href': '/core/genesis/1/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfragen")
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde")
        self.assertPresence("Zur Zeit liegen keine Veranstaltungs-Anfragen vor")
        self.assertNonPresence("Zur Zeit liegen keine Mailinglisten-Anfragen vor")
        self.traverse({'href': '/core/genesis/1/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'event'
        self.submit(f)
        self.assertTitle("Accountanfragen")
        self.assertNonPresence("Zur Zeit liegen keine Veranstaltungs-Anfragen vor")
        self.assertPresence("Zur Zeit liegen keine Mailinglisten-Anfragen vor")
        f = self.response.forms['genesiseventapprovalform1']
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.logout()
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "long_saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        new_user = {
            'id': 9,
            'username': "zorro@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertPresence("12345")

    def test_genesis_ml(self):
        user = USER_DICT['anton']
        self.get('/')
        self.traverse({'href': '/core/genesis/request'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "ml"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertPresence("Zur Zeit liegen keine Veranstaltungs-Anfragen vor")
        self.assertNonPresence("Zur Zeit liegen keine Mailinglisten-Anfragen vor")
        f = self.response.forms['genesismlapprovalform1']
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = None
        for line in mail.split('\n'):
            if line.startswith('[1] '):
                link = line[4:]
        link = quopri.decodestring(link).decode('utf-8')
        self.logout()
        self.get(link)
        self.assertTitle("Neues Passwort setzen")
        new_password = "long_saFe_37pass"
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        new_user = {
            'id': 11,
            'username': "zelda@example.cde",
            'password': new_password,
            'display_name': "Zelda",
            'given_names': "Zelda",
            'family_name': "Zeruda-Hime",
        }
        self.login(new_user)
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("Zelda Zeruda-Hime")

    def test_log(self):
        ## First: generate data
        self.test_set_foto()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Start', 'href': '^/d?b?/?$'},
                      {'href': '/core/log'})
        self.assertTitle("Account-Log [0–1]")
