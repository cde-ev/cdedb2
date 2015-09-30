#!/usr/bin/env python3

import unittest
import webtest

from test.common import as_users, USER_DICT, FrontendTest
from cdedb.query import QueryOperators

class TestCdEFrontend(FrontendTest):
    @as_users("anton", "berta")
    def test_index(self, user):
        self.traverse({'href': '/cde/$'})

    @as_users("anton", "berta")
    def test_showuser(self, user):
        self.traverse({'href': '/core/self/show'})
        self.assertTitle("{} {}".format(user['given_names'],
                                        user['family_name']))
        if user['id'] == 2:
            self.assertIn('PfingstAkademie', self.response.text)

    @as_users("berta")
    def test_changedata(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/cde/self/change'})
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

    @as_users("anton")
    def test_adminchangedata(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.traverse({'href': '/cde/user/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "3.4.1933"
        self.submit(f)
        self.assertIn("Zelda", self.response)
        self.assertTitle("Bertålotta Beispiel")
        self.assertIn("1933-04-03", self.response)

    @as_users("anton")
    def test_validation(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.traverse({'href': '/cde/user/2/adminchange'})
        f = self.response.forms['changedataform']
        f['display_name'] = "Zelda"
        f['birthday'] = "garbage"
        self.submit(f, check_notification=False)
        self.assertIn("Zelda", self.response)
        self.assertTitle("Administration -- Bertålotta Beispiel bearbeiten")
        self.assertIn("errorInput", self.response)

    def test_changelog(self):
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'}, {'href': '/cde/self/change'})
        f = self.response.forms['changedataform']
        f['family_name'] = "Ganondorf"
        self.submit(f, check_notification=False)
        self.assertIn(user['family_name'], self.response.text)
        self.assertNotIn('Ganondorf', self.response.text)
        self.logout()
        user = USER_DICT["anton"]
        self.login(user)
        self.traverse({'description': '^CdE$'}, {'href': '/cde/changelog/list'})
        self.assertTitle("Änderungen (zurzeit 1 zu begutachten)")
        self.traverse({'href': '/cde/user/2/changelog/inspect'})
        f = self.response.forms['ackchangeform']
        self.submit(f)
        self.assertTitle("Änderungen (zurzeit 0 zu begutachten)")
        self.logout()
        user = USER_DICT["berta"]
        self.login(user)
        self.traverse({'href': '/core/self/show'})
        self.assertNotIn(user['family_name'], self.response.text)
        self.assertIn('Ganondorf', self.response.text)

    def test_consent(self):
        user = USER_DICT["garcia"]
        self.login(user)
        self.assertTitle("Einwilligung zur Mitgliedersuche")
        f = self.response.forms['toplaterform']
        self.submit(f)
        self.assertTitle("CdE Datenbank")
        self.traverse({'href': '/core/self/show'},
                      {'href': '/cde/self/consent'})
        f = self.response.forms['ackconsentform']
        self.submit(f)
        self.assertIn("successNotification", self.response.text)

    @as_users("anton", "berta")
    def test_get_foto(self, user):
        response = self.app.get('/cde/foto/e83e5a2d36462d6810108d6a5fb556dcc6ae210a580bfe4f6211fe925e61ffbec03e425a3c06bea24333cc17797fc29b047c437ef5beb33ac0f570c6589d64f9')
        self.assertTrue(response.body.startswith(b"\x89PNG"))
        self.assertTrue(len(response.body) > 10000)

    @as_users("anton", "berta")
    def test_set_foto(self, user):
        self.traverse({'href': '/core/self/show'}, {'href': '/foto/change'})
        f = self.response.forms['setfotoform']
        f['foto'] = webtest.Upload("/tmp/cdedb-store/testfiles/picture.png")
        self.submit(f)
        self.assertIn('foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', self.response.text)
        with open('/tmp/cdedb-store/foto/58998c41853493e5d456a7e94ee2cff9d1f95e125661f01317853ebfd4d031c72b4cfe499bc51038d9602e7ffb289fcf852cec00ee3aaba4958e160a794bd63d', 'rb') as f:
            blob = f.read()
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertTrue(len(blob) > 10000)

    @as_users("anton", "berta")
    def test_member_search_one(self, user):
        self.traverse({'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertIn("Im Garten 77", self.response.text)

    @as_users("anton", "berta")
    def test_member_search_accents(self, user):
        self.traverse({'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_given_names,display_name'] = "Berta"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertIn("Im Garten 77", self.response.text)

    @as_users("anton", "berta")
    def test_member_search(self, user):
        self.traverse({'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_event_id'] = 1
        self.submit(f, button="updateform")
        f = self.response.forms['membersearchform']
        f['qval_username'] = "@example"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")

    @as_users("anton", "berta")
    def test_member_search_fulltext(self, user):
        self.traverse({'href': '/cde/search/member'})
        self.assertTitle("Mitgliedersuche")
        f = self.response.forms['membersearchform']
        f['qval_fulltext'] = "876 @example.cde"
        self.submit(f)
        self.assertTitle("\nMitgliedersuche -- 2 Mitglieder gefunden\n")
        self.assertIn("Anton", self.response.text)
        self.assertIn("Bertålotta", self.response.text)

    @as_users("anton")
    def test_user_search(self, user):
        self.traverse({'description': '^CdE$'}, {'href': '/cde/search/user/form'})
        self.assertTitle("CdE Nutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_address'] = 'Garten'
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("\nCdE Nutzersuche -- 1 Ergebnis gefunden\n")
        self.assertIn("persona_id=2", self.response.text)

    @as_users("anton")
    def test_user_search_csv(self, user):
        self.traverse({'description': '^CdE$'}, {'href': '/cde/search/user/form'})
        self.assertTitle("CdE Nutzersuche")
        f = self.response.forms['usersearchform']
        f['qval_address'] = 'a[rm]'
        f['qsel_member_data.persona_id'].checked = True
        f['qsel_birthday'].checked = True
        f['qsel_decided_search'].checked = True
        f['qsel_free_form'].checked = True
        f['qsel_given_names'].checked = True
        f['qord_primary'] = "member_data.persona_id"
        self.response = f.submit("CSV")
        expectation = '''member_data.persona_id;given_names;birthday;free_form;decided_search
2;Bertålotta;1981-02-11;Jede Menge Gefasel         Gut verteilt        Über mehrere Zeilen;True
3;Charly C.;1984-05-13;;True
4;Daniel D.;1963-02-19;;False
6;Ferdinand F.;1988-01-01;;True
'''.encode('utf-8')
        self.assertEqual(expectation, self.response.body)

    @as_users("anton")
    def test_archived_user_search(self, user):
        self.traverse({'description': '^CdE$'}, {'href': '/cde/search/archiveduser/form'})
        self.assertTitle("CdE Archivsuche")
        f = self.response.forms['usersearchform']
        f['qval_birthday'] = '31.12.2000'
        f['qop_birthday'] = QueryOperators.less.value
        for field in f.fields:
            if field.startswith('qsel_'):
                f[field].checked = True
        self.submit(f)
        self.assertTitle("\nCdE Archivsuche -- 1 Ergebnis gefunden\n")
        self.assertIn("Hell", self.response.text)

    @as_users("anton")
    def test_show_archived_user(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-8-G"
        self.submit(f)
        self.assertTitle("Archivzugriff -- Hades Hell")

    @as_users("anton")
    def test_toggle_activity(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertTrue(self.response.lxml.get_element_by_id('activity_checkbox').checked)
        f = self.response.forms['activitytoggleform']
        self.submit(f)
        self.assertFalse(self.response.lxml.get_element_by_id('activity_checkbox').checked)

    @as_users("anton")
    def test_modify_membership(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTrue(self.response.lxml.get_element_by_id('membership_checkbox').checked)
        self.assertIn("Daten sind für andere Mitglieder sichtbar.", self.response.text)
        self.traverse({'href': '/membership/change'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertFalse(self.response.lxml.get_element_by_id('membership_checkbox').checked)
        self.traverse({'href': '/membership/change'})
        f = self.response.forms['modifymembershipform']
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertTrue(self.response.lxml.get_element_by_id('membership_checkbox').checked)
        self.assertIn("Daten sind nicht sichtbar.", self.response.text)

    @as_users("anton")
    def test_create_user(self, user):
        self.traverse({'description': '^CdE$'}, {'href': '/cde/user/create'})
        self.assertTitle("Neues Mitglied anlegen")
        data = {
            "username": 'zelda@example.cde',
            "title": "Dr.",
            "given_names": "Zelda",
            "family_name": "Zeruda-Hime",
            "name_supplement": 'von und zu',
            "display_name": 'Zelda',
            "birthday": "5.6.1987",
            "specialisation": "oehm",
            ## "affiliation"
            "timeline": "tja",
            "interests": "hmmmm",
            "free_form": "jaaah",
            "gender": "0",
            "telephone": "030456790",
            ## "mobile"
            "weblink": "www.zzz.cc",
            "address": "Street 7",
            "address_supplement": "on the left",
            "postal_code": "12345",
            "location": "Lynna",
            "country": "Hyrule",
            ## "address2",
            ## "address_supplement2",
            ## "postal_code2",
            ## "location2",
            ## "country2",
            "notes": "some talk",
        }
        f = self.response.forms['newuserform']
        self.assertEqual("1", self.response.lxml.get_element_by_id('input_select_status').value)
        self.assertFalse(self.response.lxml.get_element_by_id('input_checkbox_trial_member').checked)
        self.assertFalse(self.response.lxml.get_element_by_id('input_checkbox_bub_search').checked)
        self.assertTrue(self.response.lxml.get_element_by_id('input_checkbox_cloud_account').checked)
        f['status'] = 0
        f['trial_member'].checked = True
        f['bub_search'].checked = True
        f['cloud_account'].checked = False
        for key, value in data.items():
            f.set(key, value)
        self.submit(f)
        self.assertTitle("Zelda Zeruda-Hime")
        self.assertIn("12345", self.response.text)
        self.assertIn("Probemitgliedschaft", self.response.text)
        self.assertIn("Daten sind für andere Mitglieder sichtbar.", self.response.text)

    @as_users("anton")
    def test_lastschrift_index(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn("generatetransactionform2", self.response.text)

    @as_users("anton", "berta")
    def test_lastschrift_show(self, user):
        self.traverse({'href': '/cde/search/member'})
        f = self.response.forms['membersearchform']
        f['qval_family_name,birth_name'] = "Beispiel"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        self.assertTitle("Einzugsermächtigungen (Bertålotta Beispiel)")
        if user['id'] == 1:
            self.assertIn("revokeform", self.response.text)
            self.assertIn("receiptform3", self.response.text)
        else:
            self.assertNotIn("revokeform", self.response.text)
            self.assertNotIn("receiptform3", self.response.text)

    @as_users("anton")
    def test_lastschrift_generate_transactions(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionsform']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)

    @as_users("anton")
    def test_lastschrift_generate_single_transaction(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        self.submit(f, check_notification=False)
        with open("/tmp/cdedb-store/testfiles/sepapain.xml", 'rb') as f:
            expectation = f.read().split(b'\n')
        exceptions = (5, 6, 14, 28, 66,)
        for index, line in enumerate(self.response.body.split(b'\n')):
            if index not in exceptions:
                self.assertEqual(expectation[index], line)

    @as_users("anton")
    def test_lastschrift_transaction_rollback(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactionsuccessform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertIn("17.50€", self.response.text)
        self.traverse({'href': '/cde/user/2/lastschrift'})
        f = self.response.forms['transactionrollbackform4']
        self.submit(f)
        self.assertIn("Keine aktive Einzugsermächtigung", self.response.text)
        self.traverse({'href': '^/$'})
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.assertIn("12.50€", self.response.text)

    @as_users("anton")
    def test_lastschrift_transaction_cancel(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactioncancelform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertIn('generatetransactionform2', self.response.text)
        self.assertNotIn('transactionsuccessform4', self.response.text)

    @as_users("anton")
    def test_lastschrift_transaction_failure(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['generatetransactionform2']
        saved = self.response
        self.submit(f, check_notification=False)
        self.response = saved
        self.traverse({'href': '/cde/lastschrift$'})
        f = self.response.forms['transactionfailureform4']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.text)
        self.assertNotIn('transactionsuccessform4', self.response.text)

    @as_users("anton")
    def test_lastschrift_skip(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/lastschrift$'})
        self.assertTitle("Übersicht Einzugsermächtigungen")
        f = self.response.forms['skiptransactionform2']
        self.submit(f)
        self.assertTitle("Übersicht Einzugsermächtigungen")
        self.assertNotIn('generatetransactionform2', self.response.text)
        self.assertNotIn('transactionsuccessform', self.response.text)

    @as_users("anton")
    def test_lastschrift_create(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-3-F"
        self.submit(f)
        self.assertTitle("Charly C. Clown")
        self.traverse({'href': '/cde/user/3/lastschrift'})
        self.assertIn("Keine aktive Einzugsermächtigung", self.response.text)
        self.traverse({'href': '/cde/user/3/lastschrift/create'})
        self.assertTitle("Neue Einzugsermächtigung anlegen (Charly C. Clown)")
        f = self.response.forms['createlastschriftform']
        f['amount'] = "123.45"
        f['iban'] = "DE26370205000008068900"
        f['max_dsa'] = "0.1"
        f['notes'] = "grosze Siebte: Take on me"
        self.submit(f)
        self.assertTitle("Einzugsermächtigungen (Charly C. Clown)")
        self.assertIn("revokeform", self.response.text)
        self.traverse({'href': '/cde/lastschrift/3/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("123.45", f['amount'].value)
        self.assertEqual("grosze Siebte: Take on me", f['notes'].value)

    @as_users("anton")
    def test_lastschrift_change(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'href': '/cde/user/2/lastschrift'},
                      {'href': '/cde/lastschrift/2/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("42.23", f['amount'].value)
        self.assertEqual('Dagobert Anatidae', f['account_owner'].value)
        self.assertEqual('reicher Onkel', f['notes'].value)
        f['amount'] = "27.16"
        f['account_owner'] = "Dagobert Beetlejuice"
        f['notes'] = "reicher Onkel (neu verheiratet)"
        self.submit(f)
        self.traverse({'href': '/cde/lastschrift/2/change'})
        f = self.response.forms['changelastschriftform']
        self.assertEqual("27.16", f['amount'].value)
        self.assertEqual('Dagobert Beetlejuice', f['account_owner'].value)
        self.assertEqual('reicher Onkel (neu verheiratet)', f['notes'].value)

    @as_users("anton")
    def test_lastschrift_receipt(self, user):
        f = self.response.forms['adminshowuserform']
        f['id_to_show'] = "DB-2-H"
        self.submit(f)
        self.assertTitle("Bertålotta Beispiel")
        self.traverse({'href': '/cde/user/2/lastschrift'})
        self.assertTitle("Einzugsermächtigungen (Bertålotta Beispiel)")
        f = self.response.forms['receiptform3']
        self.submit(f)
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton")
    def test_lastschrift_subscription_form(self, user):
        self.traverse({'href': '/cde'},
                      {'href': '/cde/lastschrift/subscription'})
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    def test_lastschrift_subscription_form_anonymous(self):
        self.get("/cde/lastschrift/subscription")
        self.assertTrue(self.response.body.startswith(b"%PDF"))

    @as_users("anton")
    def test_cde_meta_info(self, user):
        self.traverse({'href': '/cde'},
                      {'href': '/cde/meta'})
        self.assertTitle("Allgemeine Vereinsmetainformationen")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Bertålotta Beispiel", f["Finanzvorstand_Name"].value)
        f["Finanzvorstand_Name"] = "Zelda"
        self.submit(f)
        self.assertTitle("Allgemeine Vereinsmetainformationen")
        f = self.response.forms['changeinfoform']
        self.assertEqual("Zelda", f["Finanzvorstand_Name"].value)

    def test_cde_log(self):
        ## First: generate data
        self.test_set_foto()
        self.logout()

        ## Now check it
        self.login(USER_DICT['anton'])
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/log'})
        self.assertTitle("\nCdE allgemein -- Logs (0--1)\n")

    @as_users("anton")
    def test_changelog_meta(self, user):
        self.traverse({'description': '^CdE$'},
                      {'href': '/cde/changelog/view'})
        self.assertTitle("\nCdE Nutzerdaten -- Logs (0--7)\n")
