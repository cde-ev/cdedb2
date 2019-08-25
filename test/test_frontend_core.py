#!/usr/bin/env python3

import copy
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
                    self.response.lxml.get_element_by_id(
                        'displayname').text_content().strip())

    @as_users("anton", "berta", "emilia")
    def test_logout(self, user):
        self.assertEqual(
            user['display_name'],
            self.response.lxml.get_element_by_id(
                'displayname').text_content().strip())
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False)
        self.assertNonPresence(user['display_name'])
        self.assertIn('loginform', self.response.forms)

    @as_users("anton")
    def test_change_locale(self, user):
        # Test for german locale
        self.traverse({'href': '/core/search/user'})
        self.assertPresence("Suchmaske")
        self.assertNonPresence("Search Mask")
        # Test changing locale to english
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', False)
        self.assertPresence("Search Mask")
        self.assertNonPresence("Suchmaske")
        # Test storing of locale (via cookie)
        self.traverse({'href': '/cde/'},
                      {'href': '/cde/search/user'})
        self.assertPresence("Search Mask")
        self.assertNonPresence("Suchmaske")
        # Test changing locale back to german
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', False)
        self.assertPresence("Suchmaske")
        self.assertNonPresence("Search Mask")

    @as_users("anton", "berta", "charly", "daniel", "emilia", "ferdinand",
              "garcia", "inga", "janis", "kalif")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        self.assertPresence(user['given_names'])

    @as_users("anton")
    def test_adminshowuser(self, user):
        self.admin_view_profile('berta')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Überweisungen aus dem Ausland achte")

        self.admin_view_profile('emilia')
        self.assertNonPresence("Überweisungen aus dem Ausland achte")

    @as_users("berta")
    def test_member_profile_past_events(self, user):
        self.traverse({'href': '/core/self/show'})
        self.traverse({'description': "PfingstAkademie 2014"})
        self.traverse({'href': '/core/self/show'})
        self.traverse({'description': "Swish -- und alles ist gut"})

    @as_users("emilia")
    def test_event_profile_past_events(self, user):
        self.traverse({'href': '/core/self/show'})
        try:
            self.traverse({'description': "PfingstAkademie 2014"})
        except IndexError as e:
            self.assertTrue(self, "No matching elements found" in str(e))
        self.get('/core/self/show')
        try:
            self.traverse({'description': "Goethe zum Anfassen"})
        except IndexError as e:
            self.assertTrue(self, "No matching elements found" in str(e))

    @as_users("berta")
    def test_cppaymentinformation(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence("Überweisungen aus dem Ausland achte")

    @as_users("anton")
    def test_selectpersona(self, user):
        self.get('/core/persona/select?kind=admin_persona&phrase=din')
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
        expectation = (1, 2, 3, 4, 5, 6, 7, 9, 11)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=orga_event_user&phrase=bert&aux=1')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select?kind=pure_assembly_user&phrase=kal')
        expectation = (11,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("garcia")
    def test_selectpersona_unprivileged_event(self, user):
        self.get('/core/persona/select?kind=orga_event_user&phrase=bert&aux=1')
        expectation = (2,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("berta")
    def test_selectpersona_unprivileged_ml(self, user):
        self.get('/core/persona/select?kind=mod_ml_user&phrase=@exam&aux=1')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("janis")
    def test_selectpersona_unprivileged_ml2(self, user):
        self.get('/core/persona/select?kind=mod_ml_user&phrase=@exam&aux=2')
        expectation = (1, 2, 3)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("anton")
    def test_adminshowuser_advanced(self, user):
        for phrase, title in (("DB-2-7", "Bertålotta Beispiel"),
                              ("2", "Bertålotta Beispiel"),
                              ("Bertålotta Beispiel", "Bertålotta Beispiel"),
                              ("berta@example.cde", "Bertålotta Beispiel"),
                              ("anton@example.cde", "Anton Armin A. Administrator"),
                              ("Spielmanns", "Bertålotta Beispiel"),):
            self.traverse({'href': '^/$'})
            f = self.response.forms['adminshowuserform']
            f['phrase'] = phrase
            self.submit(f)
            self.assertTitle(title)
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['phrase'] = "nonsense asorecuhasoecurhkgdgdckgdoao"
        self.submit(f)
        self.assertTitle("CdE-Datenbank")
        self.traverse({'href': '^/$'})
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
        f['location2'] = "Hyrule"
        f['country2'] = "Arcadia"
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
    def test_change_password_zxcvbn(self, user):
        self.traverse({'href': '/core/self/show'})
        self.traverse({'href': '/core/self/password/change'})
        # Password one: Common English words
        new_password = 'dragonSecret'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence('Das ist ähnlich zu einem häufig genutzen Passwort.')
        self.assertPresence('Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        # Password two: Repeating patterns
        new_password = 'dfgdfg123'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence(' Wiederholungen wie „abcabcabc“ sind nur geringfügig schwieriger zu erraten als „abc“.')
        self.assertPresence('Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        self.assertPresence('Vermeide Wiederholungen von Wörtern und Buchstaben.')
        # Password three: Common German words
        new_password = 'wurdeGemeinde'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence('Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        self.assertPresence('Großschreibung hilft nicht wirklich.')
        # Password four: German umlauts
        new_password = 'überwährend'
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence('Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        # Password five: User-specific passwords
        new_password = (user['given_names'].replace('-', ' ').split()[0] +
                        user['family_name'].replace('-', ' ').split()[0])
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        # Password six+seven: CdE-specific passwords
        new_password = "cdeakademie"
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        new_password = "duschorgie"
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")

    @as_users("anton", "ferdinand")
    def test_change_password_zxcvbn_admin(self, user):
        self.traverse({'href': '/core/self/show'})
        self.traverse({'href': '/core/self/password/change'})
        # Strong enough for normal users, but not for admins
        new_password = 'phonebookbread'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach für einen Admin-Account.')

    @as_users("berta", "emilia")
    def test_change_password_zxcvbn_noadmin(self, user):
        self.traverse({'href': '/core/self/show'})
        self.traverse({'href': '/core/self/password/change'})
        # Strong enough for normal users, but not for admins
        new_password = 'phonebookbread'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.assertPresence('Passwort geändert.', div="notifications")

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
        new_passwords = {
            "good": "krce63koLe#$e",
            "bad": "dragonSecret"
        }
        for key, val in new_passwords.items():
            for i, u in enumerate(("anton", "berta", "emilia", "ferdinand")):
                with self.subTest(u=u):
                    self.setUp()
                    user = USER_DICT[u]
                    self.get('/')
                    self.traverse({'href': '/core/password/reset'})
                    self.assertTitle("Passwort zurücksetzen")
                    f = self.response.forms['passwordresetform']
                    f['email'] = user['username']
                    self.submit(f)
                    self.assertTitle("CdE-Datenbank")
                    if u in {"anton", "ferdinand"}:
                        mail = self.fetch_mail()[0]
                        text = mail.get_body().get_content()
                        self.assertNotIn('[1]', text)
                        self.assertIn('Sicherheitsgründe', text)
                        continue
                    mail = self.fetch_mail()[0]
                    link = self.fetch_link(mail)
                    self.get(link)
                    self.follow()
                    self.assertTitle("Neues Passwort setzen")
                    f = self.response.forms['passwordresetform']
                    f['new_password'] = val
                    f['new_password2'] = val
                    if key == 'good':
                        self.submit(f)
                        self.login(user)
                        self.assertIn('loginform', self.response.forms)
                        new_user = copy.deepcopy(user)
                        new_user['password'] = val
                        self.login(new_user)
                        self.assertNotIn('loginform', self.response.forms)
                        self.assertLogin(user['display_name'])
                    elif key == 'bad':
                        self.submit(f, check_notification=False)
                        self.assertNonPresence('Passwort zurückgesetzt.')
                        self.assertPresence('Passwort ist zu schwach.', div="notifications")

    def test_repeated_password_reset(self):
        new_password = "krce63koLe#$e"
        new_password2 = "krce63koLe#$e"
        user = USER_DICT["berta"]
        self.get('/')
        self.traverse({'href': '/core/password/reset'})
        f = self.response.forms['passwordresetform']
        f['email'] = user['username']
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
        # First reset should work
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        # Second reset with same link should fail
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertPresence("Link ist ungültig oder wurde bereits verwendet.",
                            div="notifications")

    def test_admin_reset_password(self):
        new_password = "krce63koLe#$e"
        self.setUp()
        user = USER_DICT['anton']
        self.login(user)
        self.admin_view_profile('ferdinand')
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        mail = self.fetch_mail()[0]
        self.logout()
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.assertTitle("Neues Passwort setzen")
        f = self.response.forms['passwordresetform']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        other = USER_DICT['ferdinand']
        self.login(other)
        self.assertIn('loginform', self.response.forms)
        new_other = copy.deepcopy(other)
        new_other['password'] = new_password
        self.login(new_other)
        self.assertNotIn('loginform', self.response.forms)
        self.assertLogin(other['display_name'])

    @as_users("anton", "berta", "emilia")
    def test_change_username(self, user):
        # First test with current username
        current_username = user['username']
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/username/change'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = current_username
        self.submit(f, check_notification=False)
        self.assertPresence("Muss sich von der aktuellen E-Mail-Adresse unterscheiden.")
        self.assertNonPresence("E-Mail abgeschickt!", div="notifications")
        # Now with new username
        new_username = "zelda@example.cde"
        f = self.response.forms['usernamechangeform']
        f['new_username'] = new_username
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
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
    def test_any_admin_query(self, user):
        self.admin_view_profile('garcia')
        self.traverse({'href': '/persona/7/privileges'})
        f = self.response.forms['privilegechangeform']
        f['is_ml_admin'].checked = True
        self.submit(f)
        self.admin_view_profile('berta')
        self.traverse({'href': '/persona/2/privileges'})
        f = self.response.forms['privilegechangeform']
        f['is_assembly_admin'].checked = True
        self.submit(f)
        self.get('/core/search/user')
        save = self.response
        self.response = save.click(description="Alle Admins")
        self.assertPresence("Ergebnis [4]")
        self.assertPresence("Anton Armin A.")
        self.assertPresence("Beispiel")
        self.assertPresence("Findus")
        self.assertPresence("Generalis")

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

    def test_archival_admin_requirement(self):
        self.login(USER_DICT["anton"])
        self.get("/core/persona/2/privileges")
        f = self.response.forms['privilegechangeform']
        f['is_core_admin'].checked = True
        f['is_cde_admin'].checked = True
        self.submit(f)
        self.logout()
        self.login(USER_DICT["berta"])
        self.admin_view_profile("daniel")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "Archived for testing."
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertPresence("Der Benutzer ist archiviert.")

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
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qop_given_names'] = QueryOperators.similar.value
        f['qval_given_names'] = 'des'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Hell")

    @as_users("anton")
    def test_archived_user_search2(self, user):
        self.traverse({'href': '/core/search/archiveduser'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]")
        self.assertPresence("Hell")

    @as_users("anton")
    def test_show_archived_user(self, user):
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.")

    @as_users("anton")
    def test_archive_user(self, user):
        self.admin_view_profile('charly')
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt")
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Archivierungsnotiz muss angegeben werden.",
                            div="notifications")
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt")
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Charly C. Clown")
        self.assertPresence("Der Benutzer ist archiviert.")
        self.assertNonPresence("Zirkusstadt")
        f = self.response.forms['dearchivepersonaform']
        self.submit(f)
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")

    @as_users("anton")
    def test_purge_user(self, user):
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.")
        f = self.response.forms['purgepersonaform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("N. N.")
        self.assertNonPresence("Hades")
        self.assertPresence("Der Benutzer ist archiviert.")

    @as_users("anton")
    def test_meta_info(self, user):
        self.traverse({'href': '^/$'},
                      {'href': '/meta'})
        self.assertTitle("Metadaten")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Bertålotta Beispiel", f["Finanzvorstand_Name"].value)
        f["Finanzvorstand_Name"] = "Zelda"
        self.submit(f)
        self.assertTitle("Metadaten")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Zelda", f["Finanzvorstand_Name"].value)

    def test_changelog(self):
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'}, {'href': '/core/self/change'})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        f['birth_name'] = ""
        self.submit(f, check_notification=False)
        self.assertPresence(user['family_name'])
        self.assertPresence("Gemeinser")
        self.assertNonPresence('Ganondorf')
        self.logout()
        user = USER_DICT["anton"]
        self.login(user)
        self.traverse({'href': '^/$'}, {'href': '/core/changelog/list'})
        self.assertTitle("Zu prüfende Profiländerungen [1]")
        self.traverse({'href': '/core/persona/2/changelog/inspect'})
        self.traverse({'description': 'Änderungen bearbeiten'})
        self.assertTitle("Bertålotta Ganondorf bearbeiten")
        self.get('/core/persona/2/changelog/inspect')
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Zu prüfende Profiländerungen [0]")
        self.traverse({'description': 'Nutzerdaten-Log'})
        f = self.response.forms['logshowform']
        f['reviewed_by'] = 'DB-1-9'
        self.submit(f)
        self.assertTitle('Nutzerdaten-Log [0–0]')
        self.assertPresence("Bertålotta Ganondorf")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence(user['family_name'])
        self.assertNonPresence("Gemeinser")
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
        self.assertTitle("Änderungs Historie von Bertålotta Beispiel")
        self.assertPresence(r"Gen 2\W*03.04.1933", regex=True)
        self.assertPresence(r"Gen 1\W*11.02.1981", regex=True)

    @as_users("anton")
    def test_markdown(self, user):
        self.admin_view_profile('inga')
        self.assertIn('<h4 id="CDEDB_MD_inga">', self.response.text)
        self.assertIn('<div class="toc">', self.response.text)
        self.assertIn('<li><a href="#CDEDB_MD_musik">Musik</a></li>', self.response.text)
        self.assertIn('<a class="btn btn-xs btn-warning" href="http://www.cde-ev.de">',
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
        # First check error handling by entering an invalid birthday
        f['birthday'] = "foobar"
        self.submit(f, check_notification=False)
        self.assertPresence('Validierung ', 'notifications')
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        # Now, do it right
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
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertNonPresence("zorro@example.cde")
        self.assertNonPresence("Zur Zeit liegen keine Veranstaltungs-Accountanfragen vor")
        self.assertPresence("Zur Zeit liegen keine Mailinglisten-Accountanfragen vor")
        self.traverse({'href': '/core/genesis/1/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde")
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("Zur Zeit liegen keine Veranstaltungs-Accountanfragen vor")
        self.assertNonPresence("Zur Zeit liegen keine Mailinglisten-Accountanfragen vor")
        self.traverse({'href': '/core/genesis/1/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'event'
        self.submit(f)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertNonPresence("Zur Zeit liegen keine Veranstaltungs-Accountanfragen vor")
        self.assertPresence("Zur Zeit liegen keine Mailinglisten-Accountanfragen vor")
        self.traverse({'href': '/core/genesis/1/show'})
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        f = self.response.forms['genesiseventapprovalform']
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
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
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.login(user)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertPresence("Zur Zeit liegen keine Veranstaltungs-Accountanfragen vor")
        self.assertNonPresence("Zur Zeit liegen keine Mailinglisten-Accountanfragen vor")
        f = self.response.forms['genesismlapprovalform1']
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
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

    def test_genesis_name_collision(self):
        self.get("/core/genesis/request")
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "ml"
        # Submit once
        self.submit(f)
        # Submit twice
        self.submit(f)
        self.assertPresence("Bestätigungsmail erneut versendet.",
                            div="notifications")
        self.get("/core/genesis/request")
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Berta"
        f['family_name'] = "Beispiel"
        f['username'] = "berta@example.cde"
        f['notes'] = "Gimme!"
        f['realm'] = "ml"
        # Submit once
        self.submit(f, check_notification=False)
        self.assertPresence("E-Mail-Adresse bereits vorhanden.",
                            div="notifications")
        user = USER_DICT['anton']
        self.login(user)
        self.get("/core/log")
        f = self.response.forms['logshowform']
        f['codes'] = [20]
        self.submit(f)
        self.assertTitle("Account-Log [0–0]")

    def test_genesis_postal_code(self):
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
        f['postal_code'] = "Z-12345"
        f['location'] = "Marcuria"
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl.")
        f['country'] = "Arkadien"
        self.submit(f)

    def test_genesis_birthday(self):
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
        f['birthday'] = "5.6.2222"
        f['address'] = "An der Eiche"
        f['postal_code'] = "12345"
        f['location'] = "Marcuria"
        self.submit(f, check_notification=False)
        self.assertPresence("Ein Geburtsdatum muss in der Vergangenheit liegen.")

    def test_genesis_missing_data(self):
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
        f['postal_code'] = "Z-12345"
        f['location'] = "Marcuria"
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl.")

    def test_log(self):
        ## First: generate data
        self.test_set_foto()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Index', 'href': '^/d?b?/?$'},
                      {'href': '/core/log'})
        self.assertTitle("Account-Log [0–0]")
