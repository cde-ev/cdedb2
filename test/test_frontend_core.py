#!/usr/bin/env python3

import copy
import urllib.parse
from test.common import USER_DICT, FrontendTest, as_users

import cdedb.database.constants as const
import webtest
from cdedb.query import QueryOperators


class TestCoreFrontend(FrontendTest):
    def test_login(self):
        for i, u in enumerate(("vera", "berta", "emilia")):
            with self.subTest(u=u):
                if i > 0:
                    self.setUp()
                user = USER_DICT[u]
                self.get("/")
                f = self.response.forms['loginform']
                f['username'] = user['username']
                f['password'] = user['password']
                self.submit(f, check_notification=False)
                self.assertPresence(user['display_name'], div='displayname',
                                    exact=True)

    @as_users("vera", "berta", "emilia")
    def test_logout(self, user):
        self.assertPresence(user['display_name'], div='displayname', exact=True)
        f = self.response.forms['logoutform']
        self.submit(f, check_notification=False)
        self.assertNonPresence(user['display_name'])
        self.assertIn('loginform', self.response.forms)

    @as_users("vera")
    def test_change_locale(self, user):
        # Test for german locale
        self.traverse({'description': 'Nutzer verwalten'})
        self.assertPresence("Suchmaske", div='qf_title')
        self.assertNonPresence("Search Mask")
        # Test changing locale to english
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', False)
        self.assertPresence("Search Mask", div='qf_title')
        self.assertNonPresence("Suchmaske")
        # Test storing of locale (via cookie)
        self.traverse({'description': 'Members'},
                      {'description': 'Manage Users'})
        self.assertPresence("Search Mask", div='qf_title')
        self.assertNonPresence("Suchmaske")
        # Test changing locale back to german
        f = self.response.forms['changelocaleform']
        self.submit(f, 'locale', False)
        self.assertPresence("Suchmaske", div='qf_title')
        self.assertNonPresence("Search Mask")

    @as_users("anton", "berta")
    def test_index(self, user):
        self.assertTitle("CdE-Datenbank")
        self.assertPresence("Meine Daten", div='sidebar')
        self.assertPresence("Orga-Veranstaltungen", div='orga-box')
        if user['id'] == 2:
            self.assertNonPresence("Log")
            self.assertNonPresence("Admin-Änderungen")
            self.assertNonPresence("Nutzer verwalten")
            self.assertNonPresence("Aktivenforum 2000")
            self.assertPresence("Aktivenforum 2001", div='moderator-box')
            # Check if there is actually the correct request
            self.traverse({'href': '/ml/mailinglist/7/management',
                           'description': "1 Anfrage"})
            self.traverse({'href': '/'})
            self.assertTitle("CdE-Datenbank")
        else:
            self.assertPresence("Account-Log", div='sidebar')
            self.assertPresence("Admin-Änderungen", div='sidebar')
            self.assertPresence("Nutzer verwalten", div='sidebar')
            self.assertPresence("Nutzer verwalten", div='adminshowuser-box')
            self.assertPresence("Platin-Lounge", div='moderator-box')
        self.assertPresence("Moderierte Mailinglisten", div='moderator-box')
        self.assertPresence("CdE-Party 2050", div='orga-box')
        self.assertNonPresence("Große Testakademie 2222", div='orga-box')
        self.assertPresence("Aktuelle Veranstaltungen", div='event-box')
        self.assertPresence("Große Testakademie 2222", div='event-box')
        self.assertNonPresence("CdE-Party 2050", div='event-box')
        self.assertPresence("Aktuelle Versammlungen", div='assembly-box')
        self.assertPresence("Internationaler Kongress", div='assembly-box')

    def test_anonymous_index(self):
        self.get('/')
        self.assertPresence("Anmelden")
        self.assertNonPresence("Meine Daten")

    @as_users("annika", "martin", "nina", "vera", "werner")
    def test_navigation(self, user):
        self.assertTitle("CdE-Datenbank")
        everyone = ["Index", "Übersicht", "Meine Daten",
                    "Administratorenübersicht"]
        genesis = ["Accountanfragen"]
        core_admin = ["Nutzer verwalten", "Archivsuche", "Änderungen prüfen",
                      "Account-Log", "Nutzerdaten-Log", "Metadaten"]
        meta_admin = ["Admin-Änderungen"]
        ins = []
        out = everyone + genesis + core_admin + meta_admin

        # admin of a realm without genesis cases
        if user == USER_DICT['werner']:
            ins = everyone
            out = genesis + core_admin + meta_admin
        # admin of a realm with genesis cases
        elif user in [USER_DICT['annika'], USER_DICT['nina']]:
            ins = everyone + genesis
            out = core_admin + meta_admin
        # core admin
        elif user == USER_DICT['vera']:
            ins = everyone + genesis + core_admin
            out = meta_admin
        # meta admin
        elif user == USER_DICT['martin']:
            ins = everyone + meta_admin
            out = genesis + core_admin

        for s in ins:
            self.assertPresence(s, div='sidebar')
        for s in out:
            self.assertNonPresence(s, div='sidebar')

    @as_users("anton", "berta", "charly", "daniel", "emilia", "ferdinand",
              "garcia", "inga", "janis", "kalif", "martin", "nina",
              "vera", "werner", "annika", "farin", "akira")
    def test_showuser(self, user):
        self.traverse({'description': user['display_name']})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        self.assertPresence(user['given_names'], div='title')

    @as_users("vera")
    def test_adminshowuser(self, user):
        self.admin_view_profile('berta')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("Bei Überweisungen aus dem Ausland achte bitte",
                            div='copy-paste-template')

        self.admin_view_profile('emilia')
        self.assertNonPresence("Bei Überweisungen aus dem Ausland achte bitte")

    @as_users("berta")
    def test_member_profile_past_events(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': "PfingstAkademie 2014"})
        self.assertTitle("PfingstAkademie 2014")
        self.traverse({'description': user['display_name']},
                      {'description': "Swish -- und alles ist gut"})
        self.assertTitle("Swish -- und alles ist gut (PfingstAkademie 2014)")

    @as_users("emilia")
    def test_event_profile_past_events(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertPresence("PfingstAkademie 2014")
        self.assertNoLink(content="PfingstAkademie 2014")
        self.assertNoLink(content="Goethe zum Anfassen")

    @as_users("berta")
    def test_cppaymentinformation(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence("Bei Überweisungen aus dem Ausland achte bitte")

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
        expectation = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14)
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

    @as_users("garcia", "nina")
    def test_selectpersona_ml_event(self, user):
        # Only event participants are shown
        # ml_admins are allowed to do this even if they are no orgas.
        self.get('/core/persona/select'
                 '?kind=mod_ml_user&phrase=@exam&aux=9&variant=20')
        expectation = (1, 2, 5)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)
        self.get('/core/persona/select'
                 '?kind=mod_ml_user&phrase=inga&aux=9&variant=20')
        expectation = (9,)
        reality = tuple(e['id'] for e in self.response.json['personas'])
        self.assertEqual(expectation, reality)

    @as_users("berta")
    def test_selectpersona_ml_event_403(self, user):
        self.get('/core/persona/select'
                 '?kind=mod_ml_user&phrase=@exam&aux=9&variant=20',
                 status=403)
        self.assertTitle('403: Forbidden')

    @as_users("berta", "garcia")
    def test_selectpersona_ml_assembly(self, user):
        # Only assembly participants are shown
        self.get('/core/persona/select'
                 '?kind=mod_ml_user&phrase=@exam&aux=5&variant=20')
        expectation = (1, 2, 9)
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

    @as_users("vera")
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
        self.assertPresence("Bertålotta", div='query-result')
        self.assertPresence("Emilia", div='query-result')
        self.assertPresence("Garcia", div='query-result')
        self.assertPresence("Kalif", div='query-result')

    @as_users("vera", "berta", "garcia")
    def test_changedata(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['location2'] = "Hyrule"
        f['country2'] = "Arcadia"
        f['specialisation'] = "Okarinas"
        self.submit(f)
        self.assertTitle("{} {}".format(user['given_names'], user['family_name']))
        self.assertPresence("Hyrule", div='address2')
        self.assertPresence("Okarinas", div='additional')
        self.assertPresence("(Zelda)", div='personal-information')

    @as_users("vera")
    def test_adminchangedata_other(self, user):
        self.admin_view_profile('berta')
        self.traverse({'description': 'Bearbeiten'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("vera")
    def test_adminchangedata_self(self, user):
        self.traverse({'description': user['display_name']},
                      {'href': '/core/persona/22/adminchange'})
        self.assertTitle("Vera Verwaltung bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Vera Verwaltung")
        self.assertPresence("03.04.1933", div='personal-information')

    @as_users("vera", "berta", "emilia")
    def test_change_password_zxcvbn(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Passwort ändern'})
        # Password one: Common English words
        new_password = 'dragonSecret'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence(
            'Das ist ähnlich zu einem häufig genutzen Passwort.')
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        # Password two: Repeating patterns
        new_password = 'dfgdfg123'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence(
            ' Wiederholungen wie „abcabcabc“ sind nur geringfügig schwieriger zu erraten als „abc“.')
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        self.assertPresence(
            'Vermeide Wiederholungen von Wörtern und Buchstaben.')
        # Password three: Common German words
        new_password = 'wurdeGemeinde'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
        self.assertPresence('Großschreibung hilft nicht wirklich.')
        # Password four: German umlauts
        new_password = 'überwährend'
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f, check_notification=False)
        self.assertNonPresence('Passwort geändert.')
        self.assertPresence('Passwort ist zu schwach.', div="notifications")
        self.assertPresence(
            'Füge ein oder zwei weitere Wörter hinzu. Unübliche Wörter sind besser.')
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

    @as_users("vera", "ferdinand")
    def test_change_password_zxcvbn_admin(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Passwort ändern'})
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
        self.traverse({'description': user['display_name']},
                      {'description': 'Passwort ändern'})
        # Strong enough for normal users, but not for admins
        new_password = 'phonebookbread'
        f = self.response.forms['passwordchangeform']
        f['old_password'] = user['password']
        f['new_password'] = new_password
        f['new_password2'] = new_password
        self.submit(f)
        self.assertPresence('Passwort geändert.', div="notifications")

    @as_users("vera", "berta", "emilia")
    def test_change_password(self, user):
        new_password = 'krce84#(=kNO3xb'
        self.traverse({'description': user['display_name']},
                      {'description': 'Passwort ändern'})
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
                    self.traverse({'description': 'Passwort zurücksetzen'})
                    self.assertTitle("Passwort zurücksetzen")
                    f = self.response.forms['passwordresetform']
                    f['email'] = user['username']
                    self.submit(f)
                    self.assertTitle("CdE-Datenbank")
                    mail = self.fetch_mail()[0]
                    if u in {"anton", "ferdinand"}:
                        text = mail.get_body().get_content()
                        self.assertNotIn('[1]', text)
                        self.assertIn('Sicherheitsgründe', text)
                        continue
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
                        self.assertPresence('Passwort ist zu schwach.',
                                            div="notifications")

    def test_repeated_password_reset(self):
        new_password = "krce63koLe#$e"
        new_password2 = "krce63koLe#$e"
        user = USER_DICT["berta"]
        self.get('/')
        self.traverse({'description': 'Passwort zurücksetzen'})
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
        user = USER_DICT['vera']
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

    @as_users("vera", "ferdinand")
    def test_cde_admin_reset_password(self, user):
        self.realm_admin_view_profile('berta', 'cde')
        self.assertTitle("Bertålotta Beispiel")
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        self.assertPresence("E-Mail abgeschickt.", div='notifications')
        self.assertTitle("Bertålotta Beispiel")

    @as_users("ferdinand", "nina")
    def test_ml_admin_reset_password(self, user):
        self.realm_admin_view_profile('janis', 'ml')
        self.assertTitle("Janis Jalapeño")
        f = self.response.forms['sendpasswordresetform']
        self.submit(f)
        self.assertPresence("E-Mail abgeschickt.", div='notifications')
        self.assertTitle("Janis Jalapeño")

    @as_users("vera", "berta", "emilia")
    def test_change_username(self, user):
        # First test with current username
        current_username = user['username']
        self.traverse({'description': user['display_name']},
                      {'href': '/core/self/username/change'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = current_username
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Muss sich von der aktuellen E-Mail-Adresse unterscheiden.")
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
        new_username = "bertalotta@example.cde"
        vera = USER_DICT['vera']
        self.get('/')
        self.login(vera)
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

    def test_any_admin_query(self):
        admin1 = USER_DICT["anton"]
        admin2 = USER_DICT["martin"]
        new_admin1 = USER_DICT["garcia"]
        new_admin2 = USER_DICT["berta"]
        new_privileges1 = {
            'is_ml_admin': True,
        }
        new_privileges2 = {
            'is_assembly_admin': True,
        }
        # Grant new admin privileges.
        self._approve_privilege_change(
            admin1, admin2, new_admin1, new_privileges1)
        self.logout()
        self._approve_privilege_change(
            admin1, admin2, new_admin2, new_privileges2)
        self.logout()
        # Check results of Any Admin query.
        self.login(admin1)
        self.get('/core/search/user')
        save = self.response
        self.response = save.click(description="Alle Admins")
        self.assertPresence("Ergebnis [14]", div='query-results')
        self.assertPresence("Akira", div='query-result')
        self.assertPresence("Anton Armin A.", div='query-result')
        self.assertPresence("Beispiel", div='query-result')
        self.assertPresence("Farin", div='query-result')
        self.assertPresence("Findus", div='query-result')
        self.assertPresence("Generalis", div='query-result')
        self.assertPresence("Meister", div='query-result')
        self.assertPresence("Olaf", div='query-result')
        self.assertPresence("Panther", div='query-result')
        self.assertPresence("Quintus", div='query-result')
        self.assertPresence("Neubauer", div='query-result')
        self.assertPresence("Olafson", div='query-result')
        self.assertPresence("Vera", div='query-result')
        self.assertPresence("Werner", div='query-result')

    def test_privilege_change(self):
        # Grant new admin privileges.
        new_admin = USER_DICT["berta"]
        new_admin_copy = copy.deepcopy(new_admin)
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
        }
        new_password = "ihsokdmfsod"
        self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin_copy,
            new_privileges, old_privileges, new_password=new_password)
        # Check success.
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {} {}".format(
            new_admin["given_names"], new_admin["family_name"]))
        f = self.response.forms['privilegechangeform']
        old_privileges.update(new_privileges)
        for k, v in old_privileges.items():
            self.assertEqual(f[k].checked, v)

        # Check that we can login with new credentials but not with old.
        self.logout()
        self.login(new_admin)
        self.assertPresence("Login fehlgeschlagen.", div="notifications")
        self.login(new_admin_copy)
        self.assertNonPresence("Login fehlgeschlagen.", div="notifications")
        self.assertLogin(new_admin['display_name'])

    @as_users("anton")
    def test_change_privileges_dependency_error(self, user):
        new_admin = USER_DICT["berta"]
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {} {}".format(
            new_admin["given_names"], new_admin["family_name"]))
        f = self.response.forms['privilegechangeform']
        f['is_finance_admin'] = True
        f['notes'] = "Berta ist jetzt Praktikant der Finanz Vorstände."
        self.submit(f, check_notification=False)
        self.assertPresence("Nur CdE Admins können Finanz Admin werden.",
                            div='notifications')
        f['is_cde_admin'] = True
        f['notes'] = "Dann ist Berta jetzt eben CdE und Finanz Admin."
        self.submit(f)

    def test_privilege_change_reject(self):
        # Grant new admin privileges.
        new_admin = USER_DICT["berta"]
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
        }
        self._reject_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin,
            new_privileges, old_privileges)
        # Check success.
        self.get('/core/persona/{}/privileges'.format(new_admin["id"]))
        self.assertTitle("Privilegien ändern für {} {}".format(
            new_admin["given_names"], new_admin["family_name"]))
        f = self.response.forms['privilegechangeform']
        # Check that old privileges are still active.
        for k, v in old_privileges.items():
            self.assertEqual(f[k].checked, v)

    @as_users("anton")
    def test_privilege_change_realm_restrictions(self, user):
        new_admin = USER_DICT["emilia"]
        f = self.response.forms['adminshowuserform']
        f['phrase'] = new_admin["DB-ID"]
        self.submit(f)
        self.traverse(
            {'href': '/core/persona/{}/privileges'.format(new_admin["id"])})
        self.assertTitle("Privilegien ändern für {} {}".format(
            new_admin["given_names"], new_admin["family_name"]))
        f = self.response.forms['privilegechangeform']
        self.assertNotIn('is_meta_admin', f.fields)
        self.assertNotIn('is_core_admin', f.fields)
        self.assertNotIn('is_cde_admin', f.fields)
        self.assertNotIn('is_finance_admin', f.fields)

    @as_users("anton", "vera")
    def test_invalidate_password(self, user):
        other_user_name = "berta"
        self.admin_view_profile(other_user_name)
        f = self.response.forms["invalidatepasswordform"]
        f["confirm_username"] = USER_DICT[other_user_name]["username"]
        self.submit(f)
        self.logout()
        self.login(USER_DICT[other_user_name])
        self.assertPresence("Login fehlgeschlagen.", div="notifications")

    def test_archival_admin_requirement(self):
        # First grant admin privileges to new admin.
        new_admin = copy.deepcopy(USER_DICT["berta"])
        new_privileges = {
            'is_core_admin': True,
            'is_cde_admin': True,
        }
        new_password = "ponsdfsidnsdgj"
        self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], new_admin,
            new_privileges, new_password=new_password)
        # Test archival
        self.logout()
        self.login(new_admin)
        self.admin_view_profile("daniel")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "Archived for testing."
        f["ack_delete"].checked = True
        self.submit(f)
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')

    def test_privilege_change_self_approval(self):
        user = USER_DICT["anton"]
        new_privileges = {
            'is_event_admin': False,
        }
        self._initialize_privilege_change(user, None, user, new_privileges)
        self.login(user)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': user["given_names"]})
        self.assertPresence(
            "Diese Änderung der Admin-Privilegien wurde von Dir angestoßen",
            div="notifications")
        self.assertNotIn('ackprivilegechangeform', self.response.forms)

    @as_users("anton")
    def test_meta_admin_archival(self, user):
        self.admin_view_profile("martin")
        f = self.response.forms["archivepersonaform"]
        f["note"] = "Archived for testing."
        f["ack_delete"].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Meta-Admins können nicht archiviert werden.",
                            div="notifications")
        self.assertNonPresence("Benutzer ist archiviert", div="notifications")
        self.assertPresence(USER_DICT["martin"]["username"])

    def _initialize_privilege_change(self, admin1, admin2, new_admin,
                                     new_privileges, old_privileges=None,
                                     note="For testing."):
        """Helper to initialize a privilege change."""
        self.login(admin1)
        f = self.response.forms['adminshowuserform']
        f['phrase'] = new_admin["DB-ID"]
        self.submit(f)
        self.traverse(
            {'href': '/core/persona/{}/privileges'.format(new_admin["id"])})
        self.assertTitle("Privilegien ändern für {} {}".format(
            new_admin["given_names"], new_admin["family_name"]))
        f = self.response.forms['privilegechangeform']
        if old_privileges:
            for k, v in old_privileges.items():
                self.assertEqual(v, f[k].checked)
        for k, v in new_privileges.items():
            f[k].checked = v
        f['notes'] = note
        self.submit(f)
        self.logout()

    def _approve_privilege_change(self, admin1, admin2, new_admin,
                                  new_privileges, old_privileges=None,
                                  note="For testing.", new_password=None):
        """Helper to make a user an admin."""
        self._initialize_privilege_change(
            admin1, admin2, new_admin, new_privileges, old_privileges)
        # Confirm privilege change.
        self.login(admin2)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': new_admin["given_names"] + " " +
                                      new_admin["family_name"]})
        f = self.response.forms["ackprivilegechangeform"]
        self.submit(f)
        self.assertPresence("Änderung wurde übernommen.", div="notifications")
        if new_password:
            mail = self.fetch_mail()[0]
            link = self.fetch_link(mail)
            self.get(link)
            f = self.response.forms["passwordresetform"]
            f["new_password"] = new_password
            f["new_password2"] = new_password
            self.submit(f)
            # Only do this with a deepcopy of the user!
            new_admin['password'] = new_password

    def _reject_privilege_change(self, admin1, admin2, new_admin,
                                 new_privileges, old_privileges=None,
                                 note="For testing."):
        """Helper to reject a privilege change."""
        self._initialize_privilege_change(
            admin1, admin2, new_admin, new_privileges, old_privileges)
        # Confirm privilege change.
        self.login(admin2)
        self.traverse({'description': "Admin-Änderungen"},
                      {'description': new_admin["given_names"] + " " +
                                      new_admin["family_name"]})
        f = self.response.forms["nackprivilegechangeform"]
        self.submit(f)
        self.assertPresence("Änderung abgelehnt.", div="notifications")

    @as_users("vera")
    def test_toggle_activity(self, user):
        for i, u in enumerate(("berta", "charly", "daniel", "emilia", "garcia",
                               "inga", "janis", "kalif", "lisa", "martin",
                               "olaf")):
            with self.subTest(target=u):
                self.admin_view_profile(u)
                f = self.response.forms['activitytoggleform']
                self.submit(f)
                msg = "Benutzer ist deaktiviert."
                if u in {"olaf"}:
                    self.assertNonPresence(msg)
                    self.assertPresence("Ja", div='account-active')
                else:
                    self.assertPresence(msg, div='deactivated')
                    self.assertPresence("Nein", div='account-active')
                f = self.response.forms['activitytoggleform']
                self.submit(f)
                if u in {"olaf"}:
                    self.assertPresence(msg, div='deactivated')
                    self.assertPresence("Nein", div='account-active')
                else:
                    self.assertNonPresence(msg)
                    self.assertPresence("Ja", div='account-active')

    @as_users("vera", "berta")
    def test_get_foto(self, user):
        response = self.app.get('/core/foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9')
        self.assertTrue(response.body.startswith(b"\x89PNG"))
        self.assertTrue(len(response.body) > 10000)

    @as_users("vera", "berta")
    def test_set_foto(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Profilbild ändern'})
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

    @as_users("vera", "berta")
    def test_set_foto_jpg(self, user):
        self.traverse({'description': user['display_name']},
                      {'description': 'Profilbild ändern'})
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
        self.traverse({'description': user['display_name']},)
        self.assertIn('foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', self.response.text)
        self.traverse({'description': 'Profilbild ändern'})
        f = self.response.forms['resetfotoform']
        self.submit(f)
        self.assertNotIn('foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9', self.response.text)

    @as_users("vera")
    def test_user_search(self,  user):
        self.traverse({'description': 'Nutzer verwalten'})
        self.assertTitle("Allgemeine Nutzerverwaltung")
        f = self.response.forms['queryform']
        f['qop_username'] = QueryOperators.match.value
        f['qval_username'] = 'n'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Allgemeine Nutzerverwaltung")
        self.assertPresence("Ergebnis [13]", div='query-results')
        self.assertPresence("Jalapeño", div='query-result')

    @as_users("vera")
    def test_archived_user_search(self,  user):
        self.traverse({'description': 'Archivsuche'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qop_given_names'] = QueryOperators.match.value
        f['qval_given_names'] = 'des'
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]", div='query-results')
        self.assertPresence("Hell", div='query-result')

    @as_users("vera")
    def test_archived_user_search2(self, user):
        self.traverse({'description': 'Archivsuche'})
        self.assertTitle("Archivsuche")
        f = self.response.forms['queryform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field and field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivsuche")
        self.assertPresence("Ergebnis [1]", div='query-results')
        self.assertPresence("Hell", div='query-result')

    @as_users("vera")
    def test_show_archived_user(self, user):
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')

    @as_users("vera")
    def test_archive_user(self, user):
        self.admin_view_profile('charly')
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt", div='address')
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        self.submit(f, check_notification=False)
        self.assertPresence("Archivierungsnotiz muss angegeben werden.",
                            div="notifications")
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")
        self.assertPresence("Zirkusstadt", div='address')
        f = self.response.forms['archivepersonaform']
        f['ack_delete'].checked = True
        f['note'] = "Archived for testing."
        self.submit(f)
        self.assertTitle("Charly C. Clown")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        self.assertNonPresence("Zirkusstadt")
        f = self.response.forms['dearchivepersonaform']
        self.submit(f)
        self.assertTitle("Charly C. Clown")
        self.assertNonPresence("Der Benutzer ist archiviert.")

    @as_users("vera")
    def test_purge_user(self, user):
        self.admin_view_profile('hades', check=False)
        self.assertTitle("Hades Hell")
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')
        f = self.response.forms['purgepersonaform']
        f['ack_delete'].checked = True
        self.submit(f)
        self.assertTitle("N. N.")
        self.assertNonPresence("Hades")
        self.assertPresence("Name N. N.", div='personal-information',
                            exact=True)
        self.assertPresence("Der Benutzer ist archiviert.", div='archived')

    @as_users("farin")
    def test_modify_balance(self, user):
        self.admin_view_profile('ferdinand')
        self.assertPresence("22,20 €", div='balance')
        self.assertNonPresence("Probemitgliedschaft")
        self.traverse({'description': 'Guthaben anpassen'})
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        # Test form default values
        f = self.response.forms['modifybalanceform']
        self.assertEqual(f['new_balance'].value, "22.20")
        self.assertFalse(f['trial_member'].checked)
        f['change_note'] = 'nop'
        # Test 'Nothing changed!' warning
        self.submit(f, check_notification=False)
        self.assertPresence("Keine Änderungen", div="notifications")
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        # Test missing change note entry warning
        f = self.response.forms['modifybalanceform']
        f['new_balance'] = 15.66
        self.submit(f, check_notification=False)
        self.assertPresence("Validierung fehlgeschlagen", div="notifications")
        self.assertTitle("Guthaben anpassen für Ferdinand F. Findus")
        # Test changing balance
        f = self.response.forms['modifybalanceform']
        f['new_balance'] = 15.66
        f['change_note'] = 'deduct stolen cookies'
        self.submit(f)
        self.assertPresence("15,66 €", div='balance')
        # Test changing trial membership
        self.traverse({'description': 'Guthaben anpassen'})
        f = self.response.forms['modifybalanceform']
        f['trial_member'].checked = True
        f['change_note'] = "deduct lost cookies"
        self.submit(f)
        self.assertPresence("CdE-Mitglied (Probemitgliedschaft)",
                            div='membership')
        # Test changing balance and trial membership
        self.traverse({'description': 'Guthaben anpassen'})
        f = self.response.forms['modifybalanceform']
        self.assertTrue(f['trial_member'].checked)
        f['new_balance'] = 22.22
        f['trial_member'].checked = False
        f['change_note'] = "deduct eaten cookies"
        self.submit(f)
        self.assertPresence("22,22 €", div='balance')
        self.assertNonPresence("Probemitgliedschaft")

    @as_users("vera")
    def test_meta_info(self, user):
        self.traverse({'description': 'Metadaten'})
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
        self.traverse({'description': user['display_name']},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        f['birth_name'] = ""
        self.submit(f, check_notification=False)
        self.assertPresence("Die Änderung wartet auf Bestätigung.",
                            div='notifications')
        self.assertPresence(user['family_name'], div='personal-information')
        self.assertPresence("Gemeinser", div='personal-information')
        self.assertNonPresence('Ganondorf')
        self.logout()
        user = USER_DICT["vera"]
        self.login(user)
        self.traverse({'description': 'Änderungen prüfen'})
        self.assertTitle("Zu prüfende Profiländerungen [1]")
        self.traverse({'description': 'Bertålotta Ganondorf'},
                      {'description': 'Änderungen bearbeiten'})
        self.assertTitle("Bertålotta Ganondorf bearbeiten")
        self.traverse({'description': 'Änderungen prüfen'},
                      {'description': 'Bertålotta Ganondorf'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Zu prüfende Profiländerungen [0]")
        self.traverse({'description': 'Nutzerdaten-Log'})
        f = self.response.forms['logshowform']
        f['reviewed_by'] = 'DB-22-1'
        self.submit(f)
        self.assertTitle('Nutzerdaten-Log [0–0]')
        self.assertPresence("Bertålotta Ganondorf")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'description': user['display_name']})
        self.assertNonPresence(user['family_name'])
        self.assertNonPresence("Gemeinser")
        self.assertPresence('Ganondorf', div='personal-information')

    @as_users("vera")
    def test_history(self, user):
        self.admin_view_profile('berta')
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("(Zelda)", div='personal-information')
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("03.04.1933", div='personal-information')
        self.traverse({'description': 'Änderungshistorie'})
        self.assertTitle("Änderungshistorie von Bertålotta Beispiel")
        self.assertPresence(r"Gen 2\W*03.04.1933", regex=True)
        self.assertPresence(r"Gen 1\W*11.02.1981", regex=True)

    @as_users("vera")
    def test_markdown(self, user):
        self.admin_view_profile('inga')
        self.assertIn('<h4 id="CDEDB_MD_inga">', self.response.text)
        self.assertIn('<div class="toc">', self.response.text)
        self.assertIn('<li><a href="#CDEDB_MD_musik">Musik</a></li>', self.response.text)
        self.assertIn('<a class="btn btn-xs btn-warning" href="http://www.cde-ev.de">',
                      self.response.text)

    def test_admin_overview(self):
        # Makes Berta Event + CdE Admin
        new_privileges = {
            'is_event_admin': True,
            'is_assembly_admin': True,
        }
        old_privileges = {
            'is_meta_admin': False,
            'is_core_admin': False,
            'is_cde_admin': False,
            'is_finance_admin': False,
            'is_event_admin': False,
            'is_assembly_admin': False,
            'is_ml_admin': False,
        }
        self._approve_privilege_change(
            USER_DICT["anton"], USER_DICT["martin"], USER_DICT["berta"],
            new_privileges, old_privileges)
        # Check the overview.
        self.traverse({"href": "/core/admins"})
        self.assertTitle("Administratorenübersicht")
        self.assertPresence("Anton Armin A. Administrator", div="meta")
        self.assertPresence("Martin Meiste", div="meta")
        self.assertPresence("Anton Armin A. Administrator", div="core")
        self.assertNonPresence("Martin Meister", div="core")
        self.assertNonPresence("Bertålotta Beispiel", div="core")
        self.assertPresence("Anton Armin A. Administrator", div="cde")
        self.assertPresence("Ferdinand F. Findus", div="cde")
        self.assertPresence("Anton Armin A. Administrator", div="finance")
        self.assertPresence("Ferdinand F. Findus", div="finance")
        self.assertPresence("Anton Armin A. Administrator", div="event")
        self.assertPresence("Ferdinand F. Findus", div="event")
        self.assertPresence("Bertålotta Beispiel", div="event")
        self.assertPresence("Anton Armin A. Administrator", div="assembly")
        self.assertPresence("Ferdinand F. Findus", div="assembly")
        self.assertPresence("Bertålotta Beispiel", div="assembly")
        self.logout()
        self.login(USER_DICT["janis"])
        self.traverse({'description': 'Administratorenübersicht'})
        self.assertTitle("Administratorenübersicht")
        self.assertPresence("Anton Armin A. Administrator", div="core")
        self.assertNonPresence("Bertålotta Beispiel")

    @as_users("vera")
    def test_trivial_promotion(self, user):
        self.admin_view_profile('emilia')
        self.traverse({'description': 'Bereich hinzufügen'})
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['realmselectionform']
        self.assertNotIn("event", f['target_realm'].options)
        f['target_realm'] = "cde"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Emilia E. Eventis")
        f = self.response.forms['promotionform']
        self.submit(f)
        self.assertTitle("Emilia E. Eventis")
        self.assertPresence("0,00 €", div='balance')

    @as_users("vera")
    def test_nontrivial_promotion(self, user):
        self.admin_view_profile('kalif')
        self.traverse({'description': 'Bereich hinzufügen'})
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        f = self.response.forms['realmselectionform']
        f['target_realm'] = "event"
        self.submit(f)
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        f = self.response.forms['promotionform']
        # First check error handling by entering an invalid birthday
        f['birthday'] = "foobar"
        self.submit(f, check_notification=False)
        self.assertPresence('Validierung ', div='notifications')
        self.assertTitle("Bereichsänderung für Kalif ibn al-Ḥasan Karabatschi")
        # Now, do it right
        f['birthday'] = "21.6.1977"
        f['gender'] = 1
        self.submit(f)
        self.assertTitle("Kalif ibn al-Ḥasan Karabatschi")
        self.assertPresence("21.06.1977", div='personal-information')

    @as_users("vera")
    def test_ignore_warnings_postal_code(self, user):
        self.admin_view_profile("vera")
        self.traverse({'description': 'Bearbeiten \\(normal\\)'})
        f = self.response.forms['changedataform']
        f['postal_code'] = "ABC-123"
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['changedataform']
        self.submit(f, button="ignore_warnings")
        self.assertTitle("Vera Verwaltung")
        self.traverse({'description': 'Bearbeiten \\(mit Adminrechten\\)'})
        f = self.response.forms['changedataform']
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['changedataform']
        self.submit(f, button="ignore_warnings")
        self.get("/core/genesis/request")
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        f['given_names'] = "Zelda"
        f['family_name'] = "Zeruda-Hime"
        f['username'] = "zelda@example.cde"
        f['notes'] = "for testing"
        f['birthday'] = "2000-01-01"
        f['address'] = "Auf dem Hügel"
        f['postal_code'] = "ABC-123"
        f['location'] = "Überall"
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['genesisform']
        self.submit(f, button="ignore_warnings")
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.traverse({'description': 'Accountanfragen'},
                      {'description': 'Details'},
                      {'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        self.assertNonPresence("Warnungen ignorieren")
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl")
        self.assertPresence("Warnungen ignorieren")
        f = self.response.forms['genesismodifyform']
        self.submit(f, button="ignore_warnings")
        f = self.response.forms['genesiseventapprovalform']
        self.submit(f)

    def _genesis_request(self, data):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in data.items():
            f[field] = entry
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        return None

    ML_GENESIS_DATA = {
        'given_names': "Zelda", 'family_name': "Zeruda-Hime",
        'username': "zelda@example.cde", 'notes': "Gimme!", 'realm': "ml"
    }

    EVENT_GENESIS_DATA = ML_GENESIS_DATA.copy()
    EVENT_GENESIS_DATA.update({
        'realm': "event", 'gender': 1, 'birthday': "1987-06-05",
        'address': "An der Eiche", 'postal_code': "12345",
        'location': "Marcuria", 'country': "Arkadien"
    })

    CDE_GENESIS_DATA = EVENT_GENESIS_DATA.copy()
    CDE_GENESIS_DATA.update({
        'realm': "cde"
    })

    def test_genesis_event(self):
        self._genesis_request(self.EVENT_GENESIS_DATA)

        user = USER_DICT['vera']
        self.login(user)
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde", div='request-1001')
        self.assertNonPresence("zorro@example.cde")
        self.assertNonPresence("Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.",
            div='no-ml-request')
        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde", div='username')
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.",
            div='no-event-request')
        self.assertNonPresence("Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'event'
        self.submit(f)
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertNonPresence("Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence(
            "Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.",
            div='no-ml-request')
        self.traverse({'href': '/core/genesis/1001/show'})
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
        self.assertPresence("12345", div='address')

    def test_genesis_ml(self):
        user = USER_DICT['vera']
        self._genesis_request(self.ML_GENESIS_DATA)
        self.login(user)
        self.traverse({'description': 'Accountanfrage'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde", div='request-1001')
        self.assertPresence(
            "Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.",
            div='no-event-request')
        self.assertNonPresence("Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
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

    @as_users("vera")
    def test_genesis_cde(self, user):
        self.get('/core/genesis/request')
        self.assertTitle("Account anfordern")
        self.assertPresence("Die maximale Dateigröße ist 8 MB.")
        f = self.response.forms['genesisform']
        for field, entry in self.CDE_GENESIS_DATA.items():
            f[field] = entry
        f['notes'] = ""  # Do not send this to test upload permanance.
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as datafile:
            data = datafile.read()
        f['attachment'] = webtest.Upload(
            "my_participation_certificate.pdf", data, content_type="application/pdf")
        self.submit(f, check_notification=False)
        self.assertPresence("Darf nicht leer sein.")
        self.assertPresence("Anhang my_participation_certificate.pdf")
        f = self.response.forms['genesisform']
        f['notes'] = "Gimme!"
        self.submit(f)
        mail = self.fetch_mail()[0]
        link = self.fetch_link(mail)
        self.get(link)
        self.follow()
        self.traverse({'href': '/core'},
                      {'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("zelda@example.cde")
        self.assertNonPresence("zorro@example.cde")
        self.assertPresence("Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence("Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence("Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/modify'})
        self.assertTitle("Accountanfrage bearbeiten")
        f = self.response.forms['genesismodifyform']
        f['username'] = 'zorro@example.cde'
        f['realm'] = 'ml'
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.assertPresence("Ganondorf")
        self.assertPresence("Anhang herunterladen")
        save = self.response
        self.traverse({'description': 'Anhang herunterladen'})
        with open("/tmp/cdedb-store/testfiles/form.pdf", 'rb') as f:
            self.assertEqual(f.read(), self.response.body)
        self.response = save
        self.assertNonPresence("zelda@example.cde")
        self.assertPresence("zorro@example.cde")
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence("Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence("Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/modify'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = 'cde'
        self.submit(f)
        self.traverse({'href': '/core/genesis/list'})
        self.assertTitle("Accountanfragen")
        self.assertPresence("Aktuell stehen keine Veranstaltungs-Account-Anfragen zur Bestätigung aus.")
        self.assertPresence("Aktuell stehen keine Mailinglisten-Account-Anfragen zur Bestätigung aus.")
        self.assertNonPresence("Aktuell stehen keine CdE-Mitglieds-Account-Anfragen zur Bestätigung aus.")
        self.traverse({'href': '/core/genesis/1001/show'})
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
        self.traverse({'href': '/cde'})
        self.assertTitle('CdE-Mitgliederbereich')
        self.traverse({'description': 'Sonstiges'})

    def test_genesis_name_collision(self):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.ML_GENESIS_DATA.items():
            f[field] = entry
        # Submit once
        self.submit(f)
        # Submit twice
        self.submit(f, check_notification=False)
        self.assertPresence("Bestätigungsmail erneut versendet.",
                            div="notifications")
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
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
        user = USER_DICT['vera']
        self.login(user)
        self.traverse({'description': 'Account-Log'})
        f = self.response.forms['logshowform']
        f['codes'] = [20]
        self.submit(f)
        self.assertTitle("Account-Log [0–0]")

    def test_genesis_verification_mail_resend(self):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.ML_GENESIS_DATA.items():
            f[field] = entry
        self.submit(f)
        self.assertGreater(len(self.fetch_mail()), 0)
        self.submit(f)
        self.assertPresence("Bestätigungsmail erneut versendet.", div="notifications")
        self.assertGreater(len(self.fetch_mail()), 0)

    def test_genesis_postal_code(self):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['country'] = ""
        f['postal_code'] = "Z-12345"
        self.submit(f, check_notification=False)
        self.assertPresence("Ungültige Postleitzahl.")
        f['country'] = "Arkadien"
        self.submit(f)

    def test_genesis_birthday(self):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['birthday'] = "2222-06-05"
        self.submit(f, check_notification=False)
        self.assertPresence(
            "Ein Geburtsdatum muss in der Vergangenheit liegen.")

    def test_genesis_missing_data(self):
        self.get('/')
        self.traverse({'description': 'Account anfordern'})
        self.assertTitle("Account anfordern")
        f = self.response.forms['genesisform']
        for field, entry in self.EVENT_GENESIS_DATA.items():
            f[field] = entry
        f['notes'] = ""
        self.submit(f, check_notification=False)
        self.assertPresence("Notwendige Angabe fehlt.")

    def test_genesis_modify(self):
        self._genesis_request(self.ML_GENESIS_DATA)

        admin = USER_DICT["vera"]
        self.login(admin)
        self.traverse({'description': 'Accountanfrage'},
                      {'description': 'Details'})
        self.assertTitle("Accountanfrage von Zelda Zeruda-Hime")
        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['family_name'] = "Zeruda"
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda")

        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['realm'] = "event"
        f['gender'] = "1"
        f['birthday'] = "1987-06-05"
        f['address'] = "An der Eiche"
        f['postal_code'] = "12345"
        f['location'] = "Marcuria"
        f['country'] = "Arkadien"
        self.submit(f)
        self.assertPresence("An der Eiche", div='address')
        self.assertPresence("Arkadien", div='address')

        self.traverse({'description': 'Bearbeiten'})
        f = self.response.forms['genesismodifyform']
        f['birthday'] = "1987-06-05"
        self.submit(f)
        self.assertTitle("Accountanfrage von Zelda Zeruda")
        f = self.response.forms['genesiseventapprovalform']
        self.submit(f)

    def test_resolve_api(self):
        b = urllib.parse.quote_plus('Bertålotta')
        self.get(
            '/core/api/resolve?given_names={}&family_name=Beispiel'.format(b),
            headers={'X-CdEDB-API-token': 'secret'})
        self.assertEqual(self.response.json, ["berta@example.cde"])
        self.get(
            '/core/api/resolve?given_names=Anton&family_name=Administrator',
            headers={'X-CdEDB-API-token': 'secret'})
        self.assertEqual(self.response.json, ["anton@example.cde"])
        self.get('/core/api/resolve', status=403)

    def test_log(self):
        user = USER_DICT['vera']
        # First: generate data
        # request and create two new accounts
        self._genesis_request(self.ML_GENESIS_DATA)
        self._genesis_request(self.EVENT_GENESIS_DATA)
        self.login(user)
        self.traverse({'description': 'Accountanfragen'})
        f = self.response.forms['genesismlapprovalform1']
        self.submit(f)
        f = self.response.forms['genesiseventapprovalform1']
        self.submit(f)

        # make janis assembly user
        self.admin_view_profile('janis')
        self.traverse({'description': 'Bereich hinzufügen'})
        f = self.response.forms['realmselectionform']
        f['target_realm'] = "assembly"
        self.submit(f)
        f = self.response.forms['promotionform']
        self.submit(f)

        # change berta's user name
        self.admin_view_profile('berta')
        self.traverse({'href': '/username/adminchange'})
        f = self.response.forms['usernamechangeform']
        f['new_username'] = "bertalotta@example.cde"
        self.submit(f)

        # Now check it
        self.traverse({'description': 'Index'},
                      {'description': 'Account-Log'})
        self.assertTitle("Account-Log [1–12 von 12]")
        f = self.response.forms["logshowform"]
        f["codes"] = [const.CoreLogCodes.genesis_verified.value,
                      const.CoreLogCodes.realm_change.value,
                      const.CoreLogCodes.username_change.value]
        self.submit(f)
        self.assertPresence("Bereiche geändert.")
        self.assertPresence("zelda@example.cde")
        self.assertPresence("bertalotta@example.cde")
        self.assertTitle("Account-Log [0–2]")
