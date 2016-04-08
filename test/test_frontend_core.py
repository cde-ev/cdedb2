#!/usr/bin/env python3

import unittest
import copy
import quopri

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
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        berta = USER_DICT['berta']
        self.assertTitle("Bertålotta Beispiel")

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
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        f['realm'] = "core"
        self.submit(f)
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("1933-04-03")

    @as_users("anton")
    def test_adminchangedata2(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-1-J"
        f['realm'] = "core"
        self.submit(f)
        self.traverse({'href': '/core/persona/1/adminchange'})
        self.assertTitle("Anton Armin A. Administrator bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Anton Armin A. Administrator")
        self.assertPresence("1933-04-03")

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
                self.assertLogin(user['display_name'])

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
        self.assertLogin(new_berta['display_name'])

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
        self.assertLogin(new_berta['display_name'])

    @as_users("anton")
    def test_privilege_change(self,  user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
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
        self.assertPresence("Jalapeño")

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
        self.assertPresence("Hell")

    @as_users("anton")
    def test_archived_user_search2(self, user):
        self.traverse({'href': '/core/search/archiveduser/form'})
        self.assertTitle("Archivnutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("Archivnutzersuche -- 1 Ergebnis gefunden")
        self.assertPresence("Hell")

    @as_users("anton")
    def test_show_archived_user(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-8-G"
        f['realm'] = "cde"
        self.submit(f)
        self.assertTitle("Archivzugriff -- Hades Hell")

    @as_users("anton")
    def test_batch_admission(self, user):
        self.traverse({'href': '/core/persona/admission$'})
        self.assertTitle("Accounts anlegen")
        f = self.response.forms['admissionform']
        with open("/tmp/cdedb-store/testfiles/batch_admission.csv") as datafile:
            f['accounts'] = datafile.read()
        self.submit(f, check_notification=False)

        ## first round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1 ")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {} ".format(i))
            output.append(head)
        head, _ = content.split(" Das Format ist".format(i))
        output.append(head)
        expectation = (
            ("Problem bei given_names: Mustn't be empty.",
             "Problem bei pevent_id: No input supplied."),
            tuple(),
            ("Problem: Lines 3 and 4 are the same.",),
            ("Problem: Lines 3 and 4 are the same.",),
            ("Warnung bei persona: Doppelgangers found.",),
            ("Warnung bei persona: Doppelgangers found.",),
            ("Warnung bei persona: Doppelgangers found.",),
            ("Warnung bei course: No course available.",),
            ("Problem bei pevent_id: No event found.",
             "Warnung bei course: No course available.",),
            ("Problem bei pcourse_id: No course found.",),
            ("Problem bei birthday: day is out of range for month",
             " Problem bei birthday: 'Mandatory key missing.'"),
            ("Problem bei postal_code: Invalid german postal code.",),
            ("Problem: Lines 13 and 14 are the same.",),
            ("Problem: Lines 13 and 14 are the same.",),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertIn(piece, out)
        for i in range(14):
            if i in (1, 7):
                expectation = '0'
            else:
                expectation = None
            self.assertEqual(expectation, f['resolution{}'.format(i)].value)
        inputdata = f['accounts'].value
        f['resolution0'] = 1
        f['resolution2'] = 1
        f['resolution3'] = 1
        f['resolution4'] = 4
        f['doppelganger_id4'] = '2'
        f['resolution5'] = 3
        f['doppelganger_id5'] = '4'
        f['resolution6'] = 2
        f['doppelganger_id6'] = '5'
        inputdata = inputdata.replace("pa99", "pa14")
        inputdata = inputdata.replace("Doomed course from hell", "Swish -- und alles ist gut")
        inputdata = inputdata.replace("31.02.1981", "21.02.1981")
        inputdata = inputdata.replace("00000", "07751")
        f['resolution12'] = 1
        f['resolution13'] = 1
        f['accounts'] = inputdata
        self.submit(f, check_notification=False)

        ## second round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1 ")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {} ".format(i))
            output.append(head)
        head, _ = content.split(" Das Format ist".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            ("Problem bei doppelganger: Doppelganger not a CdE-Account.",),
            tuple(),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            tuple(),
            tuple(),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertIn(piece, out)
        nonexpectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            ("Problem bei pevent_id: No event found.",
             "Warnung bei course: No course available.",),
            ("Problem bei pcourse_id: No course found.",),
            ("Problem bei birthday: day is out of range for month",
             " Problem bei birthday: 'Mandatory key missing.'"),
            ("Problem bei postal_code: Invalid german postal code.",),
            tuple(),
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertNotIn(piece, out)
        f['resolution6'] = 0
        f['resolution8'] = 0
        f['resolution9'] = 0
        f['resolution10'] = 0
        f['resolution11'] = 0
        self.submit(f, check_notification=False)

        ## third round
        self.assertPresence("Validieren")
        self.assertNonPresence("Anlegen")
        f = self.response.forms['admissionform']
        content = self.response.lxml.xpath("//div[@id='{}']".format("content"))[0].text_content()
        _, content = content.split(" Zeile 1 ")
        output = []
        for i in range(2, 15):
            head, content = content.split(" Zeile {} ".format(i))
            output.append(head)
        head, _ = content.split(" Das Format ist".format(i))
        output.append(head)
        expectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            ("Problem bei doppelganger: Doppelganger choice doesn't fit resolution.",),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            )
        for ex, out in zip(expectation, output):
            for piece in ex:
                self.assertIn(piece, out)
        nonexpectation = (
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            tuple(),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            ("Warnung: Entry changed.",),
            tuple(),
            tuple(),
            )
        for nonex, out in zip(nonexpectation, output):
            for piece in nonex:
                self.assertNotIn(piece, out)
        f['resolution6'] = 1
        f['doppelganger_id6'] = ''
        self.assertEqual('', f['finalized'].value)
        self.submit(f, check_notification=False)

        ## fourth round
        self.assertPresence("Anlegen")
        self.assertNonPresence("Validieren")
        f = self.response.forms['admissionform']
        self.assertEqual('True', f['finalized'].value)
        self.submit(f)
        self.assertPresence("Created 6 accounts.", div="notifications")

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
        self.assertTitle("Änderungen (zurzeit 1 zu begutachten)")
        self.traverse({'href': '/core/persona/2/changelog/inspect'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Änderungen (zurzeit 0 zu begutachten)")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'})
        self.assertNonPresence(user['family_name'])
        self.assertPresence('Ganondorf')

    @as_users("anton")
    def test_history(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        f['realm'] = "core"
        self.submit(f)
        self.traverse({'href': '/core/persona/2/adminchange'})
        self.assertTitle("Bertålotta Beispiel bearbeiten")
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertPresence("Zelda")
        self.assertTitle("Bertålotta Beispiel")
        self.assertPresence("1933-04-03")
        self.traverse({'href': '/core/persona/2/history'})
        self.assertTitle("Geschichte von Bertålotta Beispiel")
        self.assertPresence("2: 1933-04-03")
        self.assertPresence("1: 1981-02-11")
        element = self.response.lxml.xpath("//select[@name='birthday']")[0]
        self.assertEqual('2', element.value)

    def test_log(self):
        ## First: generate data
        self.test_admin_password_reset()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': 'Start', 'href': '^/d?b?/?$'},
                      {'href': '/core/log'})
        self.assertTitle("\nAccounts -- Logs (0--2)\n")
